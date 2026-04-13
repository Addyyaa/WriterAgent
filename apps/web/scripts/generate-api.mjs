import fs from "node:fs/promises";
import path from "node:path";

import openapiTS from "openapi-typescript";

const backend = (process.env.BACKEND_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const targetDir = path.resolve(process.cwd(), "generated/api");
const openapiPath = path.join(targetDir, "openapi.json");
const typesPath = path.join(targetDir, "openapi-types.ts");

const res = await fetch(`${backend}/openapi.json`);
if (!res.ok) {
  throw new Error(`Failed to fetch OpenAPI: ${res.status}`);
}
const doc = await res.json();
await fs.mkdir(targetDir, { recursive: true });
await fs.writeFile(openapiPath, JSON.stringify(doc, null, 2), "utf8");

const output = await openapiTS(doc);
await fs.writeFile(typesPath, output, "utf8");

console.log(`generated: ${typesPath}`);
