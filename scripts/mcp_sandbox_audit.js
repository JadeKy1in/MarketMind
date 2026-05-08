#!/usr/bin/env node
/**
 * MCP Sandbox Audit Script
 * 
 * 零信任安全审查：检查沙盒部署的 MCP 技能包的源码安全
 * 审查维度：
 *  - package.json 异常依赖检查
 *  - 网络外发请求检测 (fetch, axios, http.request)
 *  - 文件系统越权访问检测
 *  - 可疑的 process.env 读取
 */

const fs = require('fs');
const path = require('path');

const SANDBOX_ROOT = path.resolve(__dirname, '..', 'mcp_sandbox', 'skills');
const SUSPICIOUS_DEPENDENCIES = [
  'puppeteer', 'selenium-webdriver', 'playwright', 'child_process',
  'remote', 'ssh2', 'netcat', 'nmap', 'tcp-ping'
];
const SUSPICIOUS_PATTERNS = [
  { pattern: /fetch\(/g, severity: 'WARN', desc: 'HTTP fetch 外发请求' },
  { pattern: /axios\.(get|post|put|delete)/g, severity: 'WARN', desc: 'axios 外发请求' },
  { pattern: /http\.request\(/g, severity: 'WARN', desc: 'Node http.request' },
  { pattern: /require\(['"](child_process|net)['"]\)/g, severity: 'HIGH', desc: '系统命令/网络模块' },
  { pattern: /process\.env\./g, severity: 'INFO', desc: '环境变量读取' },
  { pattern: /fs\.(write|append|unlink|rm|rename)/g, severity: 'INFO', desc: '文件写入操作' },
  { pattern: /exec\(|execSync\(|spawn\(/g, severity: 'HIGH', desc: '命令执行' },
  { pattern: /eval\(/g, severity: 'HIGH', desc: '动态代码执行' },
];

let hasIssues = false;

function auditSkill(skillDir) {
  const name = path.basename(skillDir);
  console.log(`\n===== 审计: ${name} =====`);
  
  // 1. 检查 package.json
  const pkgPath = path.join(skillDir, 'package.json');
  if (!fs.existsSync(pkgPath)) {
    console.log(`  [SKIP] 无 package.json`);
    return;
  }
  
  const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'));
  console.log(`  版本: ${pkg.version || 'N/A'}`);
  console.log(`  许可证: ${pkg.license || 'N/A'}`);
  console.log(`  作者: ${pkg.author || 'N/A'}`);
  
  // 依赖安全检查
  const deps = { ...pkg.dependencies, ...pkg.devDependencies };
  for (const [dep, ver] of Object.entries(deps)) {
    if (SUSPICIOUS_DEPENDENCIES.some(s => dep.includes(s))) {
      console.log(`  [HIGH] 可疑依赖: ${dep}@${ver}`);
      hasIssues = true;
    }
  }
  console.log(`  总依赖数: ${Object.keys(deps).length}`);
  
  // 2. 源码扫描
  const srcDir = path.join(skillDir, 'dist');
  if (!fs.existsSync(srcDir)) {
    console.log(`  [SKIP] 无 dist/ 目录`);
    return;
  }
  
  const files = [];
  function walkDir(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith('node_modules')) walkDir(fullPath);
      } else if (entry.name.endsWith('.js')) {
        files.push(fullPath);
      }
    }
  }
  walkDir(srcDir);
  
  for (const file of files) {
    const content = fs.readFileSync(file, 'utf-8');
    const relPath = path.relative(skillDir, file);
    
    for (const check of SUSPICIOUS_PATTERNS) {
      const matches = content.match(check.pattern);
      if (matches) {
        console.log(`  [${check.severity}] ${relPath}: ${matches.length}x ${check.desc}`);
        if (check.severity === 'HIGH') hasIssues = true;
      }
    }
  }
  
  console.log(`  源码文件数: ${files.length}`);
}

function main() {
  console.log('========================================');
  console.log('  MCP Sandbox 安全审计脚本 v1.0');
  console.log('========================================');
  
  const skills = fs.readdirSync(SANDBOX_ROOT, { withFileTypes: true })
    .filter(d => d.isDirectory())
    .map(d => path.join(SANDBOX_ROOT, d.name));
  
  console.log(`找到 ${skills.length} 个技能包\n`);
  
  for (const skill of skills) {
    auditSkill(skill);
  }
  
  console.log('\n========================================');
  if (hasIssues) {
    console.log('  ⚠️  发现安全警告，请人工复查');
    process.exitCode = 1;
  } else {
    console.log('  ✅ 安全审查通过');
  }
  console.log('========================================');
}

main();