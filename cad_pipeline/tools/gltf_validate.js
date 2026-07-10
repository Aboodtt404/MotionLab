// Wraps the Khronos gltf-validator Node API → prints the report JSON to stdout.
const fs = require('fs');
const validator = require(process.env.GLTF_VALIDATOR_PATH || 'gltf-validator');
const file = process.argv[2];
const bytes = new Uint8Array(fs.readFileSync(file));
validator.validateBytes(bytes)
  .then((r) => { process.stdout.write(JSON.stringify(r)); })
  .catch((e) => { process.stdout.write(JSON.stringify({error: String(e)})); process.exit(2); });
