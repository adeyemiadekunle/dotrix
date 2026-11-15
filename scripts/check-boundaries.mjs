// Parse actual module syntax, including dynamic import/require. No regex over comments or strings.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = fileURLToPath(new URL("..", import.meta.url));

function workspace(repo = root) {
  const packages = [];
  for (const kind of ["apps", "packages"]) {
    for (const dir of fs.readdirSync(path.join(repo, kind))) {
      const folder = path.join(repo, kind, dir);
      const manifest = path.join(folder, "package.json");
      if (fs.existsSync(manifest)) packages.push({ folder, kind, ...JSON.parse(fs.readFileSync(manifest, "utf8")) });
    }
  }
  return packages;
}

export function inspect(source, filename, owner, packages) {
  const failures = [];
  const tree = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true);
  const declared = new Set([
    owner.name,
    ...Object.keys(owner.dependencies ?? {}),
    ...Object.keys(owner.devDependencies ?? {}),
    ...Object.keys(owner.peerDependencies ?? {}),
    ...Object.keys(owner.optionalDependencies ?? {}),
  ]);
  function check(specifier) {
    const destination = specifier.startsWith(".") || path.isAbsolute(specifier) ? path.resolve(path.dirname(filename), specifier) : null;
    if (destination) {
      const repo = path.resolve(owner.folder, "../..");
      const relative = path.relative(path.join(repo, "apps"), destination);
      if (
        relative &&
        !relative.startsWith("..") &&
        !path.isAbsolute(relative) &&
        !(destination === owner.folder || destination.startsWith(owner.folder + path.sep))
      ) {
        failures.push(`cross-application filesystem import ${specifier}`);
        return;
      }
    }
    const other = packages.find((pkg) =>
      destination
        ? destination === pkg.folder || destination.startsWith(pkg.folder + path.sep)
        : specifier === pkg.name || specifier.startsWith(pkg.name + "/"),
    );
    if (!other || other.name === owner.name) return;
    if (other.kind === "apps") failures.push(`application ${owner.name} cannot import application ${other.name}`);
    else if (destination) failures.push(`use ${other.name}'s public exports instead of a relative cross-package import`);
    else if (!declared.has(other.name)) failures.push(`${other.name} must be declared in ${owner.name}'s dependencies`);
    if (specifier.startsWith(other.name + "/src/")) failures.push(`use ${other.name}'s public exports, not /src`);
  }
  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier))
      check(node.moduleSpecifier.text);
    if (
      ts.isCallExpression(node) &&
      (node.expression.kind === ts.SyntaxKind.ImportKeyword || (ts.isIdentifier(node.expression) && node.expression.text === "require")) &&
      node.arguments[0] &&
      ts.isStringLiteral(node.arguments[0])
    )
      check(node.arguments[0].text);
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return failures;
}

function files(folder) {
  if (!fs.existsSync(folder)) return [];
  return fs.readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const filename = path.join(folder, entry.name);
    return entry.isDirectory() ? files(filename) : /\.(?:[cm]?js|tsx?)$/.test(filename) ? [filename] : [];
  });
}

function check(repo = root) {
  const packages = workspace(repo);
  const failures = [];
  for (const pkg of packages) {
    for (const filename of files(path.join(pkg.folder, "src"))) {
      for (const issue of inspect(fs.readFileSync(filename, "utf8"), filename, pkg, packages)) failures.push(`${path.relative(repo, filename)}: ${issue}`);
    }
    for (const name of Object.keys({ ...pkg.dependencies, ...pkg.devDependencies, ...pkg.peerDependencies, ...pkg.optionalDependencies })) {
      const other = packages.find((candidate) => candidate.name === name);
      if (other?.kind === "apps") failures.push(`${pkg.name}: application ${name} is not a shared dependency`);
    }
  }
  return failures;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const failures = check();
  if (failures.length) {
    console.error(failures.join("\n"));
    process.exitCode = 1;
  } else console.log("JavaScript workspace boundaries passed");
}
