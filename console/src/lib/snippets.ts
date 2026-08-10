/** Ready-to-run request snippets with the operator's real gateway URL + key
 * pre-filled — the "first request" moment should be copy-paste, not assembly. */

const PLACEHOLDER_KEY = "$MLPAL_API_KEY";

export function curlChat(baseUrl: string, apiKey?: string): string {
  return `curl ${baseUrl}/v1/chat/completions \\
  -H "Authorization: Bearer ${apiKey ?? PLACEHOLDER_KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "mlpal",
    "messages": [{"role": "user", "content": "Hello from my gateway!"}]
  }'`;
}

export function curlMessages(baseUrl: string, apiKey?: string): string {
  return `curl ${baseUrl}/v1/messages \\
  -H "Authorization: Bearer ${apiKey ?? PLACEHOLDER_KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "mlpal",
    "max_tokens": 512,
    "messages": [{"role": "user", "content": "Hello from my gateway!"}]
  }'`;
}

export function pythonSnippet(baseUrl: string, apiKey?: string): string {
  return `# pip install openai — any OpenAI SDK works, just change base_url
from openai import OpenAI

client = OpenAI(base_url="${baseUrl}/v1", api_key="${apiKey ?? PLACEHOLDER_KEY}")
r = client.chat.completions.create(
    model="mlpal",
    messages=[{"role": "user", "content": "Hello from my gateway!"}],
)
print(r.choices[0].message.content)`;
}

export function jsSnippet(baseUrl: string, apiKey?: string): string {
  return `const r = await fetch("${baseUrl}/v1/chat/completions", {
  method: "POST",
  headers: {
    Authorization: "Bearer ${apiKey ?? PLACEHOLDER_KEY}",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: "mlpal",
    messages: [{ role: "user", content: "Hello from my gateway!" }],
  }),
});
console.log((await r.json()).content);`;
}
