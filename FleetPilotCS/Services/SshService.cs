using Renci.SshNet;
using FleetPilot.Models;

namespace FleetPilot.Services;

public class SshResult
{
    public bool Success { get; set; }
    public string Output { get; set; } = "";
    public string Error { get; set; } = "";
    public int ExitCode { get; set; }
}

public class SshService
{
    private readonly ILogger<SshService> _logger;

    public SshService(ILogger<SshService> logger)
    {
        _logger = logger;
    }

    private SshClient CreateClient(string host, int port, string username, string? password, string? keyContent)
    {
        if (!string.IsNullOrEmpty(keyContent))
        {
            using var keyStream = new MemoryStream(System.Text.Encoding.UTF8.GetBytes(keyContent));
            var keyFile = string.IsNullOrEmpty(password)
                ? new PrivateKeyFile(keyStream)
                : new PrivateKeyFile(keyStream, password);
            return new SshClient(host, port, username, keyFile);
        }
        return new SshClient(host, port, username, password ?? "");
    }

    public async Task<SshResult> ExecuteAsync(string host, int port, string username,
        string? password, string? keyContent, string command, int timeoutSeconds = 30)
    {
        return await Task.Run(() =>
        {
            try
            {
                using var client = CreateClient(host, port, username, password, keyContent);
                client.ConnectionInfo.Timeout = TimeSpan.FromSeconds(timeoutSeconds);
                client.Connect();
                using var cmd = client.CreateCommand(command);
                cmd.CommandTimeout = TimeSpan.FromSeconds(timeoutSeconds);
                var result = cmd.Execute();
                client.Disconnect();
                return new SshResult
                {
                    Success = cmd.ExitStatus == 0,
                    Output = result,
                    Error = cmd.Error,
                    ExitCode = cmd.ExitStatus ?? -1
                };
            }
            catch (Exception ex)
            {
                _logger.LogWarning("SSH error to {Host}: {Error}", host, ex.Message);
                return new SshResult { Success = false, Error = ex.Message, ExitCode = -1 };
            }
        });
    }

    public async Task<SshResult> ExecuteAsync(ServerHost host, string command, int timeoutSeconds = 30)
        => await ExecuteAsync(host.Address, host.Port, host.User, host.Password, host.SshKey, command, timeoutSeconds);

    public async Task<bool> IsOnlineAsync(string host, int port, string username,
        string? password, string? keyContent, int timeoutSeconds = 5)
    {
        var result = await ExecuteAsync(host, port, username, password, keyContent, "echo ok", timeoutSeconds);
        return result.Success && result.Output.Trim() == "ok";
    }

    public async Task<bool> IsOnlineAsync(ServerHost host)
        => await IsOnlineAsync(host.Address, host.Port, host.User, host.Password, host.SshKey);

    public async Task<string> UploadFileAsync(string host, int port, string username,
        string? password, string? keyContent, string remotePath, string content)
    {
        return await Task.Run(() =>
        {
            try
            {
                AuthenticationMethod auth = !string.IsNullOrEmpty(keyContent)
                    ? new PrivateKeyAuthenticationMethod(username,
                        new PrivateKeyFile(new MemoryStream(System.Text.Encoding.UTF8.GetBytes(keyContent))))
                    : new PasswordAuthenticationMethod(username, password ?? "");

                var connInfo = new Renci.SshNet.ConnectionInfo(host, port, username, auth);
                using var sftp = new SftpClient(connInfo);
                sftp.Connect();
                // Ensure directory exists
                var dir = Path.GetDirectoryName(remotePath);
                if (!string.IsNullOrEmpty(dir))
                {
                    try { sftp.CreateDirectory(dir); } catch { }
                }
                using var stream = new MemoryStream(System.Text.Encoding.UTF8.GetBytes(content));
                sftp.UploadFile(stream, remotePath, true);
                sftp.Disconnect();
                return "OK";
            }
            catch (Exception ex)
            {
                return $"ERROR: {ex.Message}";
            }
        });
    }
}
