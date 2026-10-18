using System;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

// Every operation needs a Bearer access token, but the connection stores the user's
// Snaplii API key. For each call this script exchanges the key for a token at
// /v2/auth/token on the same host, then forwards the original request with the token.
// The key and the token are never logged or returned.
public class Script : ScriptBase
{
    private const string ApiKeyHeader = "X-Snaplii-Api-Key";
    private const string AgentId = "copilot-studio";

    public override async Task<HttpResponseMessage> ExecuteAsync()
    {
        var request = this.Context.Request;
        string apiKey = null;
        if (request.Headers.TryGetValues(ApiKeyHeader, out var values))
        {
            apiKey = values.FirstOrDefault()?.Trim();
        }
        request.Headers.Remove(ApiKeyHeader);
        if (string.IsNullOrEmpty(apiKey))
        {
            return Message(HttpStatusCode.Unauthorized,
                "The connection has no Snaplii API key. Edit the connection and enter the key from the Snaplii app.");
        }

        var tokenRequest = new HttpRequestMessage(HttpMethod.Post, new Uri(request.RequestUri, "/v2/auth/token"))
        {
            Content = CreateJsonContent(new JObject
            {
                ["agent_id"] = AgentId,
                ["api_key"] = apiKey,
            }.ToString(Formatting.None)),
        };
        var tokenResponse = await this.Context.SendAsync(tokenRequest, this.CancellationToken).ConfigureAwait(false);
        var tokenBody = await ReadBody(tokenResponse).ConfigureAwait(false);
        var tokenJson = ParseJson(tokenBody) as JObject;
        var token = tokenJson?["access_token"]?.Type == JTokenType.String ? (string)tokenJson["access_token"] : null;
        if (!tokenResponse.IsSuccessStatusCode || string.IsNullOrEmpty(token))
        {
            this.Context.Logger.LogWarning("Snaplii sign-in failed with HTTP {Status}.", (int)tokenResponse.StatusCode);
            return SignInFailed(tokenResponse.IsSuccessStatusCode ? HttpStatusCode.Unauthorized : tokenResponse.StatusCode,
                tokenJson);
        }

        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        var response = await this.Context.SendAsync(request, this.CancellationToken).ConfigureAwait(false);
        var body = await ReadBody(response).ConfigureAwait(false);
        if (body.Length == 0)
        {
            return response;
        }
        // Some gateway replies are JSON labeled text/plain, and some errors are plain text.
        // Label JSON as JSON, and wrap plain text so every reply parses as JSON.
        var normalized = AsJson(response.StatusCode, body);
        foreach (var header in response.Headers)
        {
            normalized.Headers.TryAddWithoutValidation(header.Key, header.Value);
        }
        return normalized;
    }

    // A failed sign-in never forwards the gateway's body, which could echo what was sent.
    // Only the status, a fixed message and a well-formed error code come back.
    private static HttpResponseMessage SignInFailed(HttpStatusCode status, JObject gatewayJson)
    {
        var code = gatewayJson?["rspMsgCd"]?.Type == JTokenType.String ? (string)gatewayJson["rspMsgCd"] : null;
        var codeOk = code != null && Regex.IsMatch(code, "^[A-Z]{2,6}[0-9]{2,6}$");
        string message;
        if ((int)status >= 500)
        {
            message = "Snaplii sign-in is temporarily unavailable. Try again later.";
        }
        else if (status == HttpStatusCode.Unauthorized || status == HttpStatusCode.Forbidden)
        {
            message = "Snaplii did not accept the API key. Check the key in the Snaplii app and edit the connection.";
        }
        else
        {
            message = "Snaplii sign-in failed. Check the API key in the Snaplii app and edit the connection.";
        }
        var body = new JObject { ["message"] = message };
        if (codeOk)
        {
            body["rspMsgCd"] = code;
        }
        return new HttpResponseMessage(status) { Content = CreateJsonContent(body.ToString(Formatting.None)) };
    }

    private static async Task<string> ReadBody(HttpResponseMessage response)
    {
        return response.Content == null ? string.Empty : await response.Content.ReadAsStringAsync().ConfigureAwait(false);
    }

    private static JToken ParseJson(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }
        try
        {
            return JToken.Parse(text);
        }
        catch (JsonReaderException)
        {
            return null;
        }
    }

    private static HttpResponseMessage AsJson(HttpStatusCode status, string body)
    {
        var json = ParseJson(body) ?? new JObject { ["message"] = body.Trim() };
        return new HttpResponseMessage(status) { Content = CreateJsonContent(json.ToString(Formatting.None)) };
    }

    private static HttpResponseMessage Message(HttpStatusCode status, string message)
    {
        return new HttpResponseMessage(status)
        {
            Content = CreateJsonContent(new JObject { ["message"] = message }.ToString(Formatting.None)),
        };
    }
}
