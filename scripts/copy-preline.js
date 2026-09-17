const fs = require('fs');
const path = require('path');

const src = path.join(__dirname, '..', 'node_modules', 'preline', 'dist', 'preline.js');
const destDir = path.join(__dirname, '..', 'static', 'js', 'vendor');
const dest = path.join(destDir, 'preline.js');

if (!fs.existsSync(src)) {
  console.error('preline.js not found — run npm install first');
  process.exit(1);
}

fs.mkdirSync(destDir, { recursive: true });
fs.copyFileSync(src, dest);
console.log('Copied preline.js to static/js/vendor/preline.js');