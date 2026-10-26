const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const input = process.argv[2];
const expected = process.argv[3];
if (!input || !expected)
  throw new Error("Provide the saved OpenAPI schema and generated types");
const folder = fs.mkdtempSync(path.join(os.tmpdir(), "quarry-contract-"));
const generated = path.join(folder, "api.generated.ts");
execFileSync(
  process.execPath,
  [
    path.resolve("node_modules/openapi-typescript/bin/cli.js"),
    input,
    "-o",
    generated,
  ],
  {
    stdio: "pipe",
  },
);
execFileSync(
  process.execPath,
  [
    path.resolve("node_modules/prettier/bin/prettier.cjs"),
    "--write",
    generated,
  ],
  {
    stdio: "pipe",
  },
);
const normalize = (text) => text.replace(/\r\n/g, "\n");
if (
  normalize(fs.readFileSync(generated, "utf8")) !==
  normalize(fs.readFileSync(expected, "utf8"))
) {
  throw new Error(
    "Generated API types are stale; regenerate from the current OpenAPI schema",
  );
}
console.log("Generated frontend API types match OpenAPI");
