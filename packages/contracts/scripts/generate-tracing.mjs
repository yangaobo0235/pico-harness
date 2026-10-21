import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'
import Ajv from 'ajv'

const source = new URL('../../../contracts/tracing/api.schema.json', import.meta.url)
const output = new URL('../src/tracing/generated.ts', import.meta.url)
const validation = new URL('../src/tracing/validation.ts', import.meta.url)
const schema = JSON.parse(await readFile(source, 'utf8'))
new Ajv({ strict: false }).compile(schema)
const header = '// AUTO-GENERATED — DO NOT EDIT — run `npm run gen:contracts`.\n'
const types = header + await compile(schema, 'TracingContracts', { bannerComment: '', unknownAny: true })
// Embed the schema so production bundles never resolve repository files.
const validator = header + `import Ajv from 'ajv'\nimport type * as Contracts from './generated.js'\n\nconst schema = ${JSON.stringify(schema, null, 2)}\nconst ajv = new Ajv({ strict: false, allErrors: true })\n` +
  Object.keys(schema.definitions).map(name =>
    `export const validate${name} = ajv.compile<Contracts.${name}>({ definitions: schema.definitions, $ref: '#/definitions/${name}' })\n`
  ).join('')

for (const [target, fresh] of [[output, types], [validation, validator]]) {
  if (process.argv.includes('--check')) {
    const existing = await readFile(target, 'utf8').catch(() => '')
    if (existing !== fresh) throw new Error(`${fileURLToPath(target)} is out of date; run npm run gen:contracts`)
  } else {
    await mkdir(new URL('.', target), { recursive: true })
    await writeFile(target, fresh)
  }
}
console.log(`Tracing contracts: ${process.argv.includes('--check') ? 'in sync' : 'generated'}`)
