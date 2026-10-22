#!/usr/bin/env node
// Sanctioned results-upload tool for the document-exfiltration demo.
// Deliberately generic: it takes a file and a destination URL and trusts
// the sandbox network policy - not this script - to decide where the
// upload may go. Any HTTP response counts as reached; the demo asserts
// on server-side request counts, not on status codes.
import { readFileSync } from "node:fs";
import { basename } from "node:path";

const [file, destination] = process.argv.slice(2);
if (!file || !destination) {
  console.error("usage: node upload-results.mjs <file> <destination-url>");
  process.exit(2);
}
const body = JSON.stringify({ name: basename(file), content: readFileSync(file, "utf8") });
try {
  const response = await fetch(destination, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  console.log(`uploaded ${basename(file)}: HTTP ${response.status}`);
} catch (error) {
  console.log(`connect error: ${error.cause?.code ?? error.code ?? error.message}`);
  process.exit(1);
}
