// Analyze the import closure of console's Chat page into xianwork-visible buckets.
const fs = require("fs");
const path = require("path");

const SRC = path.resolve(__dirname, "..", "..", "console", "src");

const visited = new Set();
const external = new Set();
const internalFiles = [];

function resolveFile(fromFile, spec) {
  if (!spec.startsWith(".")) return null;
  const base = path.resolve(path.dirname(fromFile), spec);
  const candidates = [
    base,
    base + ".ts",
    base + ".tsx",
    base + ".js",
    base + ".jsx",
    path.join(base, "index.ts"),
    path.join(base, "index.tsx"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
  }
  return null;
}

function walk(file) {
  if (visited.has(file)) return;
  visited.add(file);
  let text;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    return;
  }
  internalFiles.push(file);
  const importRe = /(?:^|\n)\s*(?:import|export)\s+(?:type\s+)?[\s\S]*?from\s+['"]([^'"]+)['"]/g;
  const sideEffectRe = /(?:^|\n)\s*import\s+['"]([^'"]+)['"]/g;
  for (const regex of [importRe, sideEffectRe]) {
    let m;
    while ((m = regex.exec(text))) {
      const spec = m[1];
      const resolved = resolveFile(file, spec);
      if (resolved) {
        walk(resolved);
      } else if (!spec.startsWith(".")) {
        const pkg = spec.startsWith("@") ? spec.split("/").slice(0, 2).join("/") : spec.split("/")[0];
        external.add(pkg);
      }
    }
  }
}

const entry = path.join(SRC, "pages", "Chat", "index.tsx");
walk(entry);

const rel = (f) => path.relative(SRC, f).replace(/\\/g, "/");
const totalKB = internalFiles.reduce((s, f) => s + fs.statSync(f).size, 0);

console.log("=== INTERNAL closure (" + internalFiles.length + " files, " + (totalKB / 1024).toFixed(0) + " KB) ===");
for (const f of internalFiles.sort()) console.log(rel(f));

console.log("\n=== EXTERNAL packages (" + external.size + ") ===");
console.log([...external].sort().join("\n"));
