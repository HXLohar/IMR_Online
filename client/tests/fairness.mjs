import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

const source = await readFile(new URL('../src/fairness-algorithm.ts', import.meta.url), 'utf8')
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText
const { generateWall, parseContext } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`)
const vector = JSON.parse(await readFile(new URL('../../server/tests/fixtures/fairness_v1.json', import.meta.url), 'utf8'))
const result = await generateWall(vector.secret, vector.context)
assert.deepEqual(result.order, vector.order)
assert.deepEqual(result.wall, vector.wall)
assert.deepEqual(result.hands, vector.hands)
assert.equal(result.dealerDraw, vector.dealer_draw)
assert.equal(result.keyHash, vector.context.server_key_hash)
assert.equal(result.wallHash, vector.wall_hash)
await assert.rejects(generateWall('ff'.repeat(32), vector.context), /fairness.keyMismatch/)
await assert.rejects(generateWall(vector.secret, { ...vector.context, hand: 2 }), /fairness.wallMismatch/)
await assert.rejects(generateWall('00', vector.context), /fairness.invalidKey/)
const duplicate = structuredClone(vector.context)
duplicate.players[1].user_id = duplicate.players[0].user_id
assert.throws(() => parseContext(duplicate), /fairness.invalidContext/)
const reordered = structuredClone(vector.context)
reordered.players.reverse()
assert.throws(() => parseContext(reordered), /fairness.invalidContext/)
assert.throws(() => parseContext({ ...vector.context, version: 'unknown' }), /fairness.invalidContext/)
console.log('Fairness: cross-language vector, initial hands, commitment mismatches and invalid inputs passed.')
