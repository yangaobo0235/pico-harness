import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const posix = value => value.replaceAll('\\', '/');
const inTree = (file, tree) => file === tree || file.startsWith(`${tree}/`);

export function boundaryError(source, target, specifier) {
  if (inTree(source, 'packages/contracts/src') && (inTree(target, 'apps') || specifier.startsWith('node:'))) return 'contracts depend on an application or Node';
  if (inTree(source, 'apps/tracing-viewer/src/web') && (inTree(target, 'apps/tracing-viewer/src/server') || specifier.startsWith('node:'))) return 'browser imports a server module';
  if (inTree(source, 'apps/tracing-viewer/src/server') && (inTree(target, 'apps/tracing-viewer/src/web') || ['react', 'react-dom'].some(name => specifier === name || specifier.startsWith(`${name}/`)))) return 'server imports browser presentation';
  if (inTree(source, 'apps/tui/src/platform') && ['apps/tui/src/app', 'apps/tui/src/features'].some(tree => inTree(target, tree))) return 'platform imports application orchestration';
  if (['apps/tui/src/ui', 'apps/tui/src/shared', 'apps/tui/src/rpc'].some(tree => inTree(source, tree)) && ['apps/tui/src/app', 'apps/tui/src/features'].some(tree => inTree(target, tree))) return 'foundation imports application orchestration';
  const sourceApp = source.startsWith('apps/tui/') ? 'tui' : source.startsWith('apps/tracing-viewer/') ? 'tracing-viewer' : null;
  if (sourceApp && target.startsWith('apps/') && !target.startsWith(`apps/${sourceApp}/`)) return 'application imports another application';
  return null;
}

function files(directory) {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(path.join(directory, entry.name)) : /\.tsx?$/.test(entry.name) ? [path.join(directory, entry.name)] : []);
}

export function checkArchitecture(repository = root) {
  const findings = [];
  for (const file of ['apps/tui/src', 'apps/tracing-viewer/src', 'packages/contracts/src'].flatMap(tree => files(path.join(repository, tree)))) {
    const relative = posix(path.relative(repository, file));
    const ast = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
    function visit(node) {
      const literal = (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) ? node.moduleSpecifier
        : ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || node.expression.getText(ast) === 'require') ? node.arguments[0] : null;
      if (literal && ts.isStringLiteral(literal)) {
        const specifier = literal.text;
        const target = specifier.startsWith('.') ? posix(path.relative(repository, path.resolve(path.dirname(file), specifier))) : specifier;
        const reason = boundaryError(relative, target, specifier);
        const line = ast.getLineAndCharacterOfPosition(literal.getStart(ast)).line + 1;
        if (reason) findings.push(`${relative}:${line}: ${reason}: ${specifier}`);
      }
      ts.forEachChild(node, visit);
    }
    visit(ast);
  }
  return findings;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const findings = checkArchitecture();
  for (const finding of findings) console.error(finding);
  if (findings.length) process.exitCode = 1;
  else console.log('TypeScript architecture: OK');
}
