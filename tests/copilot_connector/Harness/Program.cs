// Runs copilot-connector/script.csx against a fake gateway: dotnet run --project tests/copilot_connector/Harness
// With the argument "staging" it calls the four operations through the script against the staging
// gateway instead; the API key is read from the terminal without echo.
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json.Linq;

const string Key = "snp_sk_live_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
const string Token = "tok-SECRET-123";
int failures = 0;
void Check(bool ok, string what) { Console.WriteLine((ok ? "PASS " : "FAIL ") + what); if (!ok) failures++; }

if (args.Length > 0 && args[0] == "staging") { return await Staging.Run(args.Length > 1 ? args[1] : "aipay.stage.snaplii.com"); }

HttpRequestMessage Op(HttpMethod m, string path, string key = Key, string json = null)
{
    var r = new HttpRequestMessage(m, "https://aipayment.snaplii.com" + path);
    if (key != null) r.Headers.TryAddWithoutValidation("X-Snaplii-Api-Key", key);
    if (json != null) r.Content = new StringContent(json, Encoding.UTF8, "application/json");
    return r;
}

async Task<(HttpResponseMessage resp, string body, FakeContext ctx)> Run(HttpRequestMessage req, Func<HttpRequestMessage, HttpResponseMessage> gateway)
{
    var ctx = new FakeContext(req, gateway);
    var script = new Script { Context = ctx, CancellationToken = CancellationToken.None };
    var resp = await script.ExecuteAsync();
    var body = resp.Content == null ? "" : await resp.Content.ReadAsStringAsync();
    return (resp, body, ctx);
}

HttpResponseMessage Reply(HttpStatusCode s, string body, string type) =>
    new HttpResponseMessage(s) { Content = new StringContent(body, Encoding.UTF8, type) };

Func<HttpRequestMessage, HttpResponseMessage> Gateway(Func<HttpRequestMessage, HttpResponseMessage> op,
    HttpResponseMessage token = null) => r =>
    r.RequestUri.AbsolutePath == "/v2/auth/token"
        ? token ?? Reply(HttpStatusCode.OK, "{\"access_token\":\"" + Token + "\",\"expires_in\":604800,\"country\":\"CA\"}", "application/json")
        : op(r);

void NoSecrets(string body, FakeContext ctx, string what)
{
    Check(!body.Contains(Key) && !body.Contains(Token), what + ": no key or token in the reply");
    Check(!ctx.Log.ToString().Contains(Key) && !ctx.Log.ToString().Contains(Token), what + ": no key or token in the log");
}

// 1. Success: JSON labeled text/plain is relabeled; the token, not the key, reaches the operation.
{
    var (resp, body, ctx) = await Run(Op(HttpMethod.Get, "/v2/balance"),
        Gateway(r => Reply(HttpStatusCode.OK, "{\"balance\":\"808.61\"}", "text/plain")));
    Check(resp.StatusCode == HttpStatusCode.OK, "success: status 200");
    Check(resp.Content.Headers.ContentType.MediaType == "application/json", "success: relabeled application/json");
    Check(JObject.Parse(body)["balance"].ToString() == "808.61", "success: body kept");
    Check(ctx.Sent.Count == 2, "success: token exchange then the operation");
    var tokenReq = ctx.Sent[0];
    Check(tokenReq.Method == HttpMethod.Post && tokenReq.RequestUri.ToString() == "https://aipayment.snaplii.com/v2/auth/token", "success: token request goes to the same host");
    var tokenBody = JObject.Parse(ctx.Bodies[0]);
    Check((string)tokenBody["api_key"] == Key && (string)tokenBody["agent_id"] == "copilot-studio", "success: token request carries the key and agent_id");
    Check(tokenReq.Content.Headers.ContentType.MediaType == "application/json", "success: token request is JSON");
    var opReq = ctx.Sent[1];
    Check(opReq.Headers.Authorization?.ToString() == "Bearer " + Token, "success: operation carries the Bearer token");
    Check(!opReq.Headers.Contains("X-Snaplii-Api-Key"), "success: the key header is removed before forwarding");
    NoSecrets(body, ctx, "success");
}

// 2. Quote: POST body and query string are forwarded unchanged.
{
    var json = "{\"orderInfo\":{\"orderType\":\"GIFT_CARD\"}}";
    var (resp, body, ctx) = await Run(Op(HttpMethod.Post, "/v2/quote?x=1", json: json),
        Gateway(r => Reply(HttpStatusCode.OK, "{\"orderAmount\":\"10.00\"}", "text/plain")));
    Check(resp.StatusCode == HttpStatusCode.OK && ctx.Sent.Count == 2, "quote: forwarded");
    Check(ctx.Sent[1].RequestUri.PathAndQuery == "/v2/quote?x=1" && ctx.Bodies[1] == json, "quote: path, query and body unchanged");
}

// 3. Missing key: 401 JSON message, nothing sent.
{
    var (resp, body, ctx) = await Run(Op(HttpMethod.Get, "/v2/balance", key: null), Gateway(r => throw new Exception("must not send")));
    Check(resp.StatusCode == HttpStatusCode.Unauthorized && ctx.Sent.Count == 0, "no key: 401 without any request");
    Check(JObject.Parse(body)["message"].ToString().Contains("no Snaplii API key"), "no key: explains how to fix");
}

// 4. Blank key header behaves like a missing one.
{
    var (resp, _, ctx) = await Run(Op(HttpMethod.Get, "/v2/balance", key: "   "), Gateway(r => throw new Exception("must not send")));
    Check(resp.StatusCode == HttpStatusCode.Unauthorized && ctx.Sent.Count == 0, "blank key: 401 without any request");
}

// 5. Key rejected with a JSON error: the status and a well-formed code come back, never the gateway's text.
{
    var err = "{\"rspMsgCd\":\"MCA2011\",\"rspMsg\":\"Invalid API key snp_sk_live_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\"}";
    var (resp, body, ctx) = await Run(Op(HttpMethod.Get, "/v2/balance"),
        Gateway(r => throw new Exception("must not call the operation"), Reply(HttpStatusCode.Unauthorized, err, "text/plain")));
    var j = JObject.Parse(body);
    Check(resp.StatusCode == HttpStatusCode.Unauthorized && ctx.Sent.Count == 1, "rejected key: 401, operation not called");
    Check((string)j["rspMsgCd"] == "MCA2011" && ((string)j["message"]).StartsWith("Snaplii did not accept the API key") && j.Count == 2, "rejected key: fixed message and the code only");
    Check(resp.Content.Headers.ContentType.MediaType == "application/json", "rejected key: JSON");
    NoSecrets(body, ctx, "rejected key that the gateway echoed");
}

// 6. Key rejected with plain text that echoes the key: fixed message, nothing echoed.
{
    var (resp, body, ctx) = await Run(Op(HttpMethod.Get, "/v2/balance"),
        Gateway(r => throw new Exception("must not call the operation"), Reply(HttpStatusCode.Forbidden, "Forbidden for " + Key, "text/plain")));
    var j = JObject.Parse(body);
    Check(resp.StatusCode == HttpStatusCode.Forbidden && j.Count == 1 && ((string)j["message"]).StartsWith("Snaplii did not accept"), "plain-text rejection: fixed message");
    NoSecrets(body, ctx, "plain-text rejection");
}

// 6b. A malformed code is dropped; a 5xx sign-in says try later.
{
    var (resp, body, _) = await Run(Op(HttpMethod.Get, "/v2/balance"),
        Gateway(r => throw new Exception("must not call the operation"), Reply(HttpStatusCode.ServiceUnavailable, "{\"rspMsgCd\":\"<b>x</b>\"}", "application/json")));
    var j = JObject.Parse(body);
    Check(resp.StatusCode == HttpStatusCode.ServiceUnavailable && j["rspMsgCd"] == null && ((string)j["message"]).Contains("temporarily unavailable"), "5xx sign-in: status kept, malformed code dropped");
}

// 7. 200 without access_token: treated as a failed sign-in, the operation is not called.
{
    var (resp, body, ctx) = await Run(Op(HttpMethod.Get, "/v2/balance"),
        Gateway(r => throw new Exception("must not call the operation"), Reply(HttpStatusCode.OK, "{\"rspMsgCd\":\"X\"}", "application/json")));
    Check(resp.StatusCode == HttpStatusCode.Unauthorized && ctx.Sent.Count == 1, "no token in 200: 401, operation not called");
}

// 8. 200 with empty body.
{
    var (resp, body, ctx) = await Run(Op(HttpMethod.Get, "/v2/balance"),
        Gateway(r => throw new Exception("must not call the operation"), Reply(HttpStatusCode.OK, "", "text/plain")));
    Check(resp.StatusCode == HttpStatusCode.Unauthorized && JObject.Parse(body)["message"] != null, "empty sign-in reply: 401 with a message");
}

// 9. Operation returns a plain-text error: status kept, wrapped as JSON.
{
    var (resp, body, ctx) = await Run(Op(HttpMethod.Get, "/v2/card-brands/CB1"),
        Gateway(r => Reply(HttpStatusCode.BadGateway, "Bad Gateway", "text/plain")));
    Check(resp.StatusCode == HttpStatusCode.BadGateway && (string)JObject.Parse(body)["message"] == "Bad Gateway" && resp.Content.Headers.ContentType.MediaType == "application/json", "plain-text error: wrapped, status kept");
}

// 10. Operation returns an empty body: passed through unchanged.
{
    var (resp, body, ctx) = await Run(Op(HttpMethod.Get, "/v2/balance"), Gateway(r => new HttpResponseMessage(HttpStatusCode.NoContent)));
    Check(resp.StatusCode == HttpStatusCode.NoContent && body == "", "empty body: passed through");
}

// 11. Array JSON (the brand list) stays an array; response headers survive.
{
    var (resp, body, ctx) = await Run(Op(HttpMethod.Get, "/v2/card-brands?channel=HOME_PAGE"), Gateway(r =>
    {
        var m = Reply(HttpStatusCode.OK, "[{\"name\":\"Coffee\"}]", "text/plain");
        m.Headers.TryAddWithoutValidation("X-Request-Id", "rid-1");
        return m;
    }));
    Check(JToken.Parse(body) is JArray && resp.Headers.GetValues("X-Request-Id").Single() == "rid-1", "array body kept, headers kept");
}

// 12. The staging run picks a card the way the client reads brand details.
{
    var sample = JToken.Parse("{\"data\":{\"cardBrandId\":\"CB1\",\"cards\":[{\"cardTemplateId\":\"CT9\",\"faceValueRules\":{\"type\":\"VARIABLE\",\"priceStart\":10,\"priceEnd\":500}}]}}");
    var (tid, price) = Staging.PickCard(sample);
    Check(tid == "CT9" && price == "10", "staging card pick: template and priceStart from faceValueRules");
    var bare = Staging.PickCard(JToken.Parse("{\"cards\":[{\"cardTemplateId\":\"CT2\",\"faceValueRules\":{\"type\":\"FIXED\",\"priceStart\":\"25.00\"}}]}"));
    Check(bare.templateId == "CT2" && bare.price == "25.00", "staging card pick: brand without a data wrapper");
}

Console.WriteLine(failures == 0 ? "ALL PASSED" : failures + " FAILED");
return failures == 0 ? 0 : 1;

class FakeContext : IScriptContext
{
    private readonly Func<HttpRequestMessage, HttpResponseMessage> _gateway;
    public FakeContext(HttpRequestMessage req, Func<HttpRequestMessage, HttpResponseMessage> gateway) { Request = req; _gateway = gateway; }
    public string CorrelationId => "test";
    public string OperationId => "op";
    public HttpRequestMessage Request { get; }
    public StringBuilder Log { get; } = new StringBuilder();
    public ILogger Logger => new SbLogger(Log);
    public List<HttpRequestMessage> Sent { get; } = new();
    public List<string> Bodies { get; } = new();
    public async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        Sent.Add(request);
        Bodies.Add(request.Content == null ? null : await request.Content.ReadAsStringAsync());
        return _gateway(request);
    }
}

class SbLogger : ILogger
{
    private readonly StringBuilder _sb;
    public SbLogger(StringBuilder sb) { _sb = sb; }
    public IDisposable BeginScope<TState>(TState state) => null;
    public bool IsEnabled(LogLevel level) => true;
    public void Log<TState>(LogLevel level, EventId id, TState state, Exception ex, Func<TState, Exception, string> f) => _sb.AppendLine(level + " " + f(state, ex));
}

static class Staging
{
    // Calls the four connector operations through the script against a real gateway.
    // The key is read from the terminal without echo and never printed.
    public static async Task<int> Run(string host)
    {
        Console.Error.Write("Snaplii API key (hidden): ");
        var key = new StringBuilder();
        while (true) { var k = Console.ReadKey(true); if (k.Key == ConsoleKey.Enter) break; if (k.Key == ConsoleKey.Backspace) { if (key.Length > 0) key.Length--; } else key.Append(k.KeyChar); }
        Console.Error.WriteLine();
        var http = new HttpClient();
        async Task<(HttpResponseMessage, string)> Call(HttpMethod m, string path, string json = null)
        {
            var req = new HttpRequestMessage(m, "https://" + host + path);
            req.Headers.TryAddWithoutValidation("X-Snaplii-Api-Key", key.ToString());
            if (json != null) req.Content = new StringContent(json, Encoding.UTF8, "application/json");
            var ctx = new LiveContext(req, http);
            var resp = await new Script { Context = ctx, CancellationToken = CancellationToken.None }.ExecuteAsync();
            var body = resp.Content == null ? "" : await resp.Content.ReadAsStringAsync();
            var leak = body.Contains(key.ToString()) || ctx.Log.ToString().Contains(key.ToString());
            Console.WriteLine($"{m} {path.Split('?')[0]} -> HTTP {(int)resp.StatusCode} {resp.Content?.Headers.ContentType?.MediaType} (calls {ctx.Calls}, key leaked: {leak})");
            return (resp, body);
        }
        int bad = 0;
        var (r1, b1) = await Call(HttpMethod.Get, "/v2/card-brands?channel=HOME_PAGE");
        var cats = JToken.Parse(b1) as JArray; bad += r1.IsSuccessStatusCode && cats != null ? 0 : 1;
        string brandId = cats?.SelectTokens("$..cardBrands[*].cardBrandId").Select(t => (string)t).FirstOrDefault();
        Console.WriteLine($"   categories {cats?.Count}, first brand {(brandId == null ? "none" : "found")}");
        var (r2, b2) = await Call(HttpMethod.Get, "/v2/card-brands/" + Uri.EscapeDataString(brandId ?? "none") + "?showDetail=true");
        bad += r2.IsSuccessStatusCode ? 0 : 1;
        var (templateId, price) = PickCard(JToken.Parse(b2));
        Console.WriteLine($"   template {(templateId == null ? "none" : "found")}, priceStart {price}");
        var (r3, b3) = await Call(HttpMethod.Get, "/v2/balance");
        bad += r3.IsSuccessStatusCode ? 0 : 1;
        Console.WriteLine($"   balance parses as JSON: {JToken.Parse(b3) is JObject}");
        if (brandId != null && templateId != null && price != null)
        {
            var quote = new JObject { ["orderInfo"] = new JObject { ["orderType"] = "GIFT_CARD", ["businessChannel"] = "APP", ["item"] = new JObject { ["itemId"] = brandId + "-" + templateId, ["price"] = price }, ["orderContext"] = new JObject { ["giftOrder"] = "false" } }, ["paymentContext"] = new JObject { ["specifiedPrimaryPaymentMethod"] = "SNAPLII_CREDIT", ["voucherOption"] = "BEST_FIT", ["cashbackOption"] = "USE" } };
            var (r4, b4) = await Call(HttpMethod.Post, "/v2/quote", quote.ToString());
            bad += r4.IsSuccessStatusCode ? 0 : 1;
            var q = JToken.Parse(b4);
            Console.WriteLine($"   quote orderAmount {q.SelectToken("$..orderAmount")}, primaryPayAmount {q.SelectToken("$..primaryPayAmount")} (a quote charges nothing)");
        }
        else { bad++; Console.WriteLine("   quote skipped: no card found"); }
        Console.WriteLine(bad == 0 ? "STAGING: ALL 4 OPERATIONS OK" : $"STAGING: {bad} PROBLEM(S)");
        return bad == 0 ? 0 : 1;
    }

    // Brand details: the brand (bare or under "data") lists cards; each card has its
    // cardTemplateId and its amounts under faceValueRules.
    public static (string templateId, string price) PickCard(JToken detail)
    {
        var brand = (detail as JObject)?["data"] as JObject ?? detail as JObject;
        var card = (brand?["cards"] as JArray)?.FirstOrDefault() as JObject;
        var rules = card?["faceValueRules"] as JObject;
        return ((string)card?["cardTemplateId"], rules?["priceStart"]?.ToString());
    }
}

class LiveContext : IScriptContext
{
    private readonly HttpClient _http;
    public LiveContext(HttpRequestMessage req, HttpClient http) { Request = req; _http = http; }
    public string CorrelationId => "staging";
    public string OperationId => "op";
    public HttpRequestMessage Request { get; }
    public StringBuilder Log { get; } = new StringBuilder();
    public ILogger Logger => new SbLogger(Log);
    public int Calls;
    public Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct) { Calls++; return _http.SendAsync(request, ct); }
}
