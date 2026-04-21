#!/usr/bin/env node
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const root = path.resolve(__dirname, '..');
const pythonScript = path.join(root, 'tools', 'graplite_scan.py');
const initScript = path.join(root, 'tools', 'graplite_init.py');
const doctorScript = path.join(root, 'tools', 'graplite_doctor.py');
const installScript = path.join(root, 'tools', 'graplite_install.py');

function runPython(script, args) {
  const python = process.env.PYTHON || 'python3';
  const result = spawnSync(python, [script, ...args], { stdio: 'inherit' });
  if (result.error) {
    console.error(result.error.message);
    process.exit(typeof result.status === 'number' ? result.status : 1);
  }
  process.exit(result.status ?? 0);
}

function printHelp() {
  console.log(`Usage:
  npx graplite-scan                 # scan current repo -> MAP.md + IMPACT.md
  npx graplite-scan scan [repo]
  npx graplite-scan init [--write-runner --write-gitignore]
  npx graplite-scan doctor
  npx graplite-scan install
  npx graplite-scan help
`);
}

const args = process.argv.slice(2);
const first = args[0] || '';

if (!first) {
  runPython(pythonScript, ['--repo', '.', '--mode', 'short']);
}

switch (first) {
  case 'scan':
  case 'analyze': {
    const repo = args[1] || '.';
    const rest = args.slice(2);
    runPython(pythonScript, ['--repo', repo, '--mode', 'short', ...rest]);
    break;
  }
  case 'project': {
    const repo = args[1] || '.';
    const rest = args.slice(2);
    runPython(pythonScript, ['--repo', repo, '--mode', 'project', ...rest]);
    break;
  }
  case 'agent': {
    const repo = args[1] || '.';
    const rest = args.slice(2);
    runPython(pythonScript, ['--repo', repo, '--mode', 'agent-claude', ...rest]);
    break;
  }
  case 'init':
    runPython(initScript, args.slice(1));
    break;
  case 'doctor':
    runPython(doctorScript, args.slice(1));
    break;
  case 'install':
    runPython(installScript, args.slice(1));
    break;
  case 'help':
  case '--help':
  case '-h':
    printHelp();
    break;
  default:
    if (fs.existsSync(first) || first === '.') {
      runPython(pythonScript, ['--repo', first, '--mode', 'short', ...args.slice(1)]);
      break;
    }
    printHelp();
    process.exit(1);
}
