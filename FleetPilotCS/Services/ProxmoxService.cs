using System.Net.Http.Headers;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using FleetPilot.Models;

namespace FleetPilot.Services;

public class VmInfo
{
    public string VmId { get; set; } = "";
    public string Name { get; set; } = "";
    public string Status { get; set; } = "";
    public int Cpus { get; set; }
    public long MaxMem { get; set; }
    public long Mem { get; set; }
    public long Disk { get; set; }
    public double Uptime { get; set; }
    public string Type { get; set; } = "qemu";
    public string Node { get; set; } = "";
    public string? Tags { get; set; }
    public double? CpuUsage { get; set; }
    public double? NetIn { get; set; }
    public double? NetOut { get; set; }
}

public class NodeInfo
{
    public string Node { get; set; } = "";
    public string Status { get; set; } = "";
    public double CpuUsage { get; set; }
    public long MaxMem { get; set; }
    public long Mem { get; set; }
    public long MaxDisk { get; set; }
    public long Disk { get; set; }
    public double Uptime { get; set; }
}

public class ProxmoxService
{
    private readonly ILogger<ProxmoxService> _logger;
    private readonly IHttpClientFactory _httpFactory;

    public ProxmoxService(ILogger<ProxmoxService> logger, IHttpClientFactory httpFactory)
    {
        _logger = logger;
        _httpFactory = httpFactory;
    }

    private HttpClient GetClient(VmEndpoint ep)
    {
        var handler = new HttpClientHandler
        {
            ServerCertificateCustomValidationCallback = ep.VerifySsl
                ? HttpClientHandler.DangerousAcceptAnyServerCertificateValidator
                : null
        };
        // Always skip SSL for Proxmox (self-signed certs are common)
        handler.ServerCertificateCustomValidationCallback =
            HttpClientHandler.DangerousAcceptAnyServerCertificateValidator;

        var client = new HttpClient(handler)
        {
            BaseAddress = new Uri($"https://{ep.Address}:{ep.Port}/api2/json/"),
            Timeout = TimeSpan.FromSeconds(15)
        };

        if (!string.IsNullOrEmpty(ep.ApiToken))
        {
            client.DefaultRequestHeaders.Authorization =
                new AuthenticationHeaderValue("PVEAPIToken", ep.ApiToken);
        }
        return client;
    }

    private async Task<string?> GetTicketAsync(VmEndpoint ep)
    {
        try
        {
            using var client = GetClient(ep);
            var form = new FormUrlEncodedContent(new[]
            {
                new KeyValuePair<string, string>("username", ep.Username ?? "root@pam"),
                new KeyValuePair<string, string>("password", ep.Password ?? "")
            });
            var resp = await client.PostAsync("access/ticket", form);
            if (!resp.IsSuccessStatusCode) return null;
            var json = JObject.Parse(await resp.Content.ReadAsStringAsync());
            return json["data"]?["ticket"]?.ToString();
        }
        catch { return null; }
    }

    public async Task<List<VmInfo>> GetVmsAsync(VmEndpoint ep)
    {
        var result = new List<VmInfo>();
        try
        {
            using var client = GetClient(ep);
            if (string.IsNullOrEmpty(ep.ApiToken))
            {
                var ticket = await GetTicketAsync(ep);
                if (ticket != null)
                    client.DefaultRequestHeaders.Add("Cookie", $"PVEAuthCookie={ticket}");
            }

            // Get nodes
            var nodesResp = await client.GetStringAsync("nodes");
            var nodesJson = JObject.Parse(nodesResp);
            var nodes = nodesJson["data"]?.ToArray() ?? Array.Empty<JToken>();

            foreach (var node in nodes)
            {
                var nodeName = node["node"]?.ToString() ?? "";
                if (!string.IsNullOrEmpty(ep.Node) && nodeName != ep.Node) continue;

                // Get QEMUs
                try
                {
                    var qemuResp = await client.GetStringAsync($"nodes/{nodeName}/qemu");
                    var qemuJson = JObject.Parse(qemuResp);
                    foreach (var vm in qemuJson["data"] ?? new JArray())
                    {
                        result.Add(new VmInfo
                        {
                            VmId = vm["vmid"]?.ToString() ?? "",
                            Name = vm["name"]?.ToString() ?? $"VM {vm["vmid"]}",
                            Status = vm["status"]?.ToString() ?? "unknown",
                            Cpus = vm["cpus"]?.Value<int>() ?? 0,
                            MaxMem = vm["maxmem"]?.Value<long>() ?? 0,
                            Mem = vm["mem"]?.Value<long>() ?? 0,
                            Disk = vm["disk"]?.Value<long>() ?? 0,
                            Uptime = vm["uptime"]?.Value<double>() ?? 0,
                            Type = "qemu",
                            Node = nodeName,
                            Tags = vm["tags"]?.ToString(),
                            CpuUsage = vm["cpu"]?.Value<double>(),
                            NetIn = vm["netin"]?.Value<double>(),
                            NetOut = vm["netout"]?.Value<double>()
                        });
                    }
                }
                catch { }

                // Get LXCs
                try
                {
                    var lxcResp = await client.GetStringAsync($"nodes/{nodeName}/lxc");
                    var lxcJson = JObject.Parse(lxcResp);
                    foreach (var ct in lxcJson["data"] ?? new JArray())
                    {
                        result.Add(new VmInfo
                        {
                            VmId = ct["vmid"]?.ToString() ?? "",
                            Name = ct["name"]?.ToString() ?? $"CT {ct["vmid"]}",
                            Status = ct["status"]?.ToString() ?? "unknown",
                            Cpus = ct["cpus"]?.Value<int>() ?? 0,
                            MaxMem = ct["maxmem"]?.Value<long>() ?? 0,
                            Mem = ct["mem"]?.Value<long>() ?? 0,
                            Disk = ct["disk"]?.Value<long>() ?? 0,
                            Uptime = ct["uptime"]?.Value<double>() ?? 0,
                            Type = "lxc",
                            Node = nodeName,
                            Tags = ct["tags"]?.ToString(),
                            CpuUsage = ct["cpu"]?.Value<double>()
                        });
                    }
                }
                catch { }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Proxmox error for {Ep}: {Error}", ep.Name, ex.Message);
        }
        return result;
    }

    public async Task<List<NodeInfo>> GetNodesAsync(VmEndpoint ep)
    {
        var result = new List<NodeInfo>();
        try
        {
            using var client = GetClient(ep);
            if (string.IsNullOrEmpty(ep.ApiToken))
            {
                var ticket = await GetTicketAsync(ep);
                if (ticket != null)
                    client.DefaultRequestHeaders.Add("Cookie", $"PVEAuthCookie={ticket}");
            }
            var resp = await client.GetStringAsync("nodes");
            var json = JObject.Parse(resp);
            foreach (var node in json["data"] ?? new JArray())
            {
                result.Add(new NodeInfo
                {
                    Node = node["node"]?.ToString() ?? "",
                    Status = node["status"]?.ToString() ?? "unknown",
                    CpuUsage = node["cpu"]?.Value<double>() ?? 0,
                    MaxMem = node["maxmem"]?.Value<long>() ?? 0,
                    Mem = node["mem"]?.Value<long>() ?? 0,
                    MaxDisk = node["maxdisk"]?.Value<long>() ?? 0,
                    Disk = node["disk"]?.Value<long>() ?? 0,
                    Uptime = node["uptime"]?.Value<double>() ?? 0
                });
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Proxmox nodes error for {Ep}: {Error}", ep.Name, ex.Message);
        }
        return result;
    }

    public async Task<bool> VmActionAsync(VmEndpoint ep, string node, string vmId, string type, string action)
    {
        // action: start, stop, reboot, suspend, resume, shutdown
        try
        {
            using var client = GetClient(ep);
            string? csrfToken = null;
            if (string.IsNullOrEmpty(ep.ApiToken))
            {
                var ticket = await GetTicketAsync(ep);
                if (ticket == null) return false;
                client.DefaultRequestHeaders.Add("Cookie", $"PVEAuthCookie={ticket}");
                // Get CSRF token
                var authResp = await client.PostAsync("access/ticket",
                    new FormUrlEncodedContent(new[]
                    {
                        new KeyValuePair<string, string>("username", ep.Username ?? "root@pam"),
                        new KeyValuePair<string, string>("password", ep.Password ?? "")
                    }));
                var authJson = JObject.Parse(await authResp.Content.ReadAsStringAsync());
                csrfToken = authJson["data"]?["CSRFPreventionToken"]?.ToString();
                if (csrfToken != null)
                    client.DefaultRequestHeaders.Add("CSRFPreventionToken", csrfToken);
            }

            var endpoint = type == "lxc"
                ? $"nodes/{node}/lxc/{vmId}/status/{action}"
                : $"nodes/{node}/qemu/{vmId}/status/{action}";

            var resp = await client.PostAsync(endpoint, new StringContent("", Encoding.UTF8, "application/json"));
            return resp.IsSuccessStatusCode;
        }
        catch (Exception ex)
        {
            _logger.LogWarning("VM action error: {Error}", ex.Message);
            return false;
        }
    }
}
