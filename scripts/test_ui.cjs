const { spawnSync } = require('node:child_process'),
  fs = require('node:fs'),
  path = require('node:path');
for (const file of fs
  .readdirSync(path.join(__dirname, '../tests'))
  .filter((f) => f.endsWith('.cjs'))) {
  const r = spawnSync(process.execPath, [path.join(__dirname, '../tests', file)], {
    stdio: 'inherit',
  });
  if (r.status) process.exit(r.status);
}
