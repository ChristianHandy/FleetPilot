using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using Microsoft.IdentityModel.Tokens;
using FleetPilot.Data;
using FleetPilot.Models;
using Microsoft.EntityFrameworkCore;

namespace FleetPilot.Services;

public class AuthService
{
    private readonly AppDbContext _db;
    private readonly IConfiguration _config;

    public AuthService(AppDbContext db, IConfiguration config)
    {
        _db = db;
        _config = config;
    }

    public async Task<LoginResponse?> LoginAsync(string username, string password)
    {
        var user = await _db.Users.FirstOrDefaultAsync(u => u.Username == username);
        if (user == null) return null;
        if (!BCrypt.Net.BCrypt.Verify(password, user.PasswordHash)) return null;

        user.LastLogin = DateTime.UtcNow;
        await _db.SaveChangesAsync();

        var token = GenerateToken(user);
        return new LoginResponse(token, user.Username, user.Role, DateTime.UtcNow.AddDays(7));
    }

    public async Task<bool> ChangePasswordAsync(int userId, string newPassword)
    {
        var user = await _db.Users.FindAsync(userId);
        if (user == null) return false;
        user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(newPassword);
        await _db.SaveChangesAsync();
        return true;
    }

    public async Task EnsureDefaultUserAsync()
    {
        if (!await _db.Users.AnyAsync())
        {
            var username = _config["Auth:DefaultUsername"] ?? "admin";
            var defaultPass = _config["Auth:DefaultPassword"];
            if (string.IsNullOrWhiteSpace(defaultPass) || defaultPass == "FleetPilot2025")
            {
                // No shared default password: generate one and leave it for the admin to read.
                defaultPass = Convert.ToBase64String(System.Security.Cryptography.RandomNumberGenerator.GetBytes(18));
                var passPath = Path.Combine(_config["DataDir"] ?? AppContext.BaseDirectory, "initial_admin_password");
                File.WriteAllText(passPath, $"{username}:{defaultPass}\n");
                if (!OperatingSystem.IsWindows())
                    File.SetUnixFileMode(passPath, UnixFileMode.UserRead | UnixFileMode.UserWrite);
                Console.WriteLine($"INFO: Generated the initial admin password in {passPath}");
            }
            _db.Users.Add(new User
            {
                Username = username,
                PasswordHash = BCrypt.Net.BCrypt.HashPassword(defaultPass),
                Role = "admin"
            });
            await _db.SaveChangesAsync();
        }
    }

    private string GenerateToken(User user)
    {
        var key = new SymmetricSecurityKey(
            Encoding.UTF8.GetBytes(_config["Jwt:Key"]!));
        var creds = new SigningCredentials(key, SecurityAlgorithms.HmacSha256);
        var claims = new[]
        {
            new Claim(ClaimTypes.NameIdentifier, user.Id.ToString()),
            new Claim(ClaimTypes.Name, user.Username),
            new Claim(ClaimTypes.Role, user.Role),
            new Claim("userId", user.Id.ToString())
        };
        var token = new JwtSecurityToken(
            issuer: "FleetPilot",
            audience: "FleetPilot",
            claims: claims,
            expires: DateTime.UtcNow.AddDays(7),
            signingCredentials: creds);
        return new JwtSecurityTokenHandler().WriteToken(token);
    }
}
