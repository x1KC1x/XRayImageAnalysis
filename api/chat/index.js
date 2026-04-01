const https = require('https');

const GATEWAY_URL = 'https://aigw.dev.dvn.com/anthropic/v1/chat/claude-sonnet-latest';

module.exports = async function (context, req) {
  // Only allow POST
  if (req.method !== 'POST') {
    context.res = { status: 405, body: { error: 'Method not allowed' } };
    return;
  }

  // Key lives ONLY in Azure Static Web App environment settings — never in code or browser
  const gatewayKey = process.env.DEVON_GATEWAY_KEY;
  if (!gatewayKey) {
    context.log.error('DEVON_GATEWAY_KEY environment variable is not set');
    context.res = {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
      body: { error: 'Gateway not configured. Contact your administrator.' }
    };
    return;
  }

  const { messages, system } = req.body || {};
  if (!messages || !Array.isArray(messages)) {
    context.res = {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
      body: { error: 'Invalid request: messages array required' }
    };
    return;
  }

  try {
    const payload = JSON.stringify({
      max_tokens: 1000,
      system: system || '',
      messages: messages
    });

    const response = await callGateway(payload, gatewayKey);

    context.res = {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
      body: response
    };
  } catch (err) {
    context.log.error('Gateway call failed:', err.message);
    context.res = {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
      body: { error: 'Failed to reach Devon AI Gateway: ' + err.message }
    };
  }
};

function callGateway(payload, key) {
  return new Promise((resolve, reject) => {
    const url = new URL(GATEWAY_URL);
    const options = {
      hostname: url.hostname,
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-KEY': key,
        'Content-Length': Buffer.byteLength(payload)
      }
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error('Invalid JSON from gateway: ' + data.substring(0, 200)));
        }
      });
    });

    req.on('error', reject);
    req.setTimeout(30000, () => {
      req.destroy();
      reject(new Error('Gateway request timed out after 30s'));
    });

    req.write(payload);
    req.end();
  });
}
