// HTTP errors prove reachability. Only a distinct, evidenced proxy denial may pass.
try {
  const response = await fetch(process.argv[2], {signal: AbortSignal.timeout(10000)});
  const body = await response.text();
  console.log(JSON.stringify({kind: 'http', status: response.status, body}));
} catch (error) {
  console.log(JSON.stringify({kind: 'transport-error', code: error.cause?.code || error.name}));
  process.exitCode = 2;
}
