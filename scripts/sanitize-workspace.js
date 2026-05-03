#!/usr/bin/env node

/**
 * Sanitize Workspace — One-Key De-Sensitization Engine
 *
 * USAGE:
 *   node scripts/sanitize-workspace.js           # Dry-run mode (default)
 *   node scripts/sanitize-workspace.js --force    # Execute mode
 *
 * WHAT IT DOES:
 *   1. Resets activeContext.md and progress.md to blank templates
 *   2. Resets projectBrief.md, productContext.md, techContext.md to blank templates
 *   3. Scans all .ts / .js / .md files for hardcoded absolute paths
 *      (e.g., "E:\AI_Studio_Workspace", "C:\Users\Administrator")
 *      and replaces them with sanitized placeholders
 *   4. Generates a summary report of all changes
 *
 * SELF-PROTECTION: This script will never scan or modify itself.
 */

const fs = require('fs');
const path = require('path');

// ============================================================
// Configuration
// ============================================================

const DRY_RUN = !process.argv.includes('--force');

const ROOT = path.resolve(__dirname, '..');

// Files to reset to blank templates
const FILES_TO_RESET = [
  {
    rel: 'memory-bank/activeContext.md',
    template: `# Active Context

## Current Session

*This file is reset by sanitize-workspace.js. Update with current session context.*

## Recent Changes

- *No recent changes recorded yet.*

## Next Steps

- *Define next steps after workspace sanitization.*

## Architecture Decisions

- *No architecture decisions recorded yet.*
`
  },
  {
    rel: 'memory-bank/progress.md',
    template: `# Progress

## What Works

- *Workspace sanitized. Update with current working features.*

## What's Left / Known Issues

- *No known issues recorded yet.*

## Memory Bank Status

- [ ] projectBrief.md — *pending*
- [ ] productContext.md — *pending*
- [ ] techContext.md — *pending*
- [ ] systemPatterns.md — *pending*
- [ ] activeContext.md — *pending*
- [ ] progress.md — *pending*
`
  },
  {
    rel: 'memory-bank/projectBrief.md',
    template: `# Project Brief

## Core Requirements

- *Define core requirements here.*

## Success Metrics

- *Define success metrics here.*

## In Scope

- *What is in scope.*

## Out of Scope

- *What is out of scope.*

## Constraints

- *List architecture constraints.*
`
  },
  {
    rel: 'memory-bank/productContext.md',
    template: `# Product Context

## Problem Statement

- *Describe the problem being solved.*

## User Experience Goals

- *Define UX goals.*

## Stakeholder Objectives

- *List stakeholder objectives.*
`
  },
  {
    rel: 'memory-bank/techContext.md',
    template: `# Technical Context

## Technology Stack

- *List technologies used.*

## Architecture Overview

- *Describe the architecture.*

## Constraints & Trade-offs

- *List technical constraints and trade-offs.*

## Known Technical Debt

- *List known technical debt items.*
`
  }
];

// Absolute path patterns to sanitize
const ABSOLUTE_PATH_REGEX = /[A-Za-z]:\\(?:[^\\:"<>|?*\x00-\x1f]+\\)*[^\\:"<>|?*\x00-\x1f]*/g;

// Sensitive patterns to look for
const SENSITIVE_PATTERNS = [
  { pattern: /C:\\Users\\[^\\]+/gi, replacement: 'C:\\Users\\<REDACTED_USER>' },
  { pattern: /E:\\AI_Studio_Workspace/gi, replacement: '<PROJECT_ROOT>' },
  { pattern: /AI_Studio_Workspace/gi, replacement: '<PROJECT_ROOT>' },
  { pattern: /Administrator/gi, replacement: '<USER>' },
  { pattern: /saoudrizwan\.claude-dev/gi, replacement: '<REDACTED_VENDOR>' },
];

// File extensions to scan for hardcoded paths
const SCAN_EXTENSIONS = ['.ts', '.js', '.md', '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini'];

// Directories to scan (recursively)
const SCAN_DIRECTORIES = [
  'src',
  'infrastructure',
  'scripts',
  'memory-bank',
];

// Patterns to skip scanning (substrings of file paths)
const SKIP_PATHS = [
  'node_modules',
  '.git',
  'coverage',
  'dist',
];

// ============================================================
// Helper Functions
// ============================================================

function shouldSkip(filePath) {
  return SKIP_PATHS.some(skip => filePath.includes(skip));
}

function walkDir(dir) {
  const results = [];
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!SKIP_PATHS.includes(entry.name)) {
          results.push(...walkDir(fullPath));
        }
      } else {
        results.push(fullPath);
      }
    }
  } catch (err) {
    // ignore permission errors
  }
  return results;
}

function isTextFile(ext) {
  return SCAN_EXTENSIONS.includes(ext);
}

function countMatches(content, regex) {
  const matches = content.match(regex);
  return matches ? matches.length : 0;
}

// ============================================================
// Phase 1: Reset Memory Bank Files
// ============================================================

let resetCount = 0;
let scanCount = 0;
let sanitizedCount = 0;
const sanitizedDetails = [];

function resetMemoryBankFiles() {
  console.log('='.repeat(70));
  console.log('PHASE 1: Resetting Memory Bank Files');
  console.log('='.repeat(70));

  for (const fileDef of FILES_TO_RESET) {
    const fullPath = path.join(ROOT, fileDef.rel);
    if (!fs.existsSync(fullPath)) {
      console.log(`  ⚠ SKIP: ${fileDef.rel} — file not found`);
      continue;
    }

    const originalContent = fs.readFileSync(fullPath, 'utf-8');
    if (!DRY_RUN) {
      fs.writeFileSync(fullPath, fileDef.template, 'utf-8');
    }
    resetCount++;
    const action = DRY_RUN ? '[DRY-RUN] Would reset' : '[EXECUTED] Reset';
    console.log(`  ${action}: ${fileDef.rel} (${originalContent.length} chars → ${fileDef.template.length} chars)`);
  }
}

// ============================================================
// Phase 2: Scan & Sanitize Hardcoded Paths
// ============================================================

function scanAndSanitizePaths() {
  console.log('\n' + '='.repeat(70));
  console.log('PHASE 2: Scanning & Sanitizing Hardcoded Paths');
  console.log('='.repeat(70));

  // Normalize self path for comparison
  const selfPath = __filename.replace(/\\/g, '/').toLowerCase();

  for (const scanDir of SCAN_DIRECTORIES) {
    const fullScanDir = path.join(ROOT, scanDir);
    if (!fs.existsSync(fullScanDir)) {
      console.log(`  ⚠ SKIP: ${scanDir}/ — directory not found`);
      continue;
    }

    const files = walkDir(fullScanDir);
    for (const filePath of files) {
      // Skip self (the sanitizer script itself)
      if (filePath.replace(/\\/g, '/').toLowerCase() === selfPath) continue;
      if (shouldSkip(filePath)) continue;
      const ext = path.extname(filePath);
      if (!isTextFile(ext)) continue;

      const relPath = path.relative(ROOT, filePath);
      let content = fs.readFileSync(filePath, 'utf-8');
      let originalContent = content;
      let changed = false;

      // Apply sensitive pattern replacements
      for (const { pattern, replacement } of SENSITIVE_PATTERNS) {
        if (content.match(pattern)) {
          content = content.replace(pattern, replacement);
          changed = true;
        }
      }

      if (changed) {
        scanCount++;
        const matchCount = countMatches(originalContent, ABSOLUTE_PATH_REGEX);
        const originalSize = Buffer.byteLength(originalContent, 'utf-8');
        const newSize = Buffer.byteLength(content, 'utf-8');
        sanitizedDetails.push({ file: relPath, matches: matchCount, originalSize, newSize });

        if (!DRY_RUN) {
          fs.writeFileSync(filePath, content, 'utf-8');
        }

        sanitizedCount += matchCount;
        const action = DRY_RUN ? '[DRY-RUN] Would sanitize' : '[EXECUTED] Sanitized';
        console.log(`  ${action}: ${relPath} (${matchCount} path(s) found)`);
      }
    }
  }
}

// ============================================================
// Phase 3: Summary Report
// ============================================================

function printSummary() {
  console.log('\n' + '='.repeat(70));
  console.log('SANITIZATION SUMMARY REPORT');
  console.log('='.repeat(70));
  console.log(`  Mode:  ${DRY_RUN ? 'DRY-RUN (no changes written)' : 'EXECUTE (changes applied)'}`);
  console.log(`  Date:  ${new Date().toISOString()}`);
  console.log('');
  console.log(`  Phase 1 — Memory Bank Resets:`);
  console.log(`    Files reset: ${resetCount}`);
  console.log('');
  console.log(`  Phase 2 — Path Sanitization:`);
  console.log(`    Files scanned: ${scanCount}`);
  console.log(`    Total paths sanitized: ${sanitizedCount}`);

  if (sanitizedDetails.length > 0) {
    console.log('');
    console.log(`  Sanitized Files Detail:`);
    console.log(`  ${'File'.padEnd(55)} ${'Matches'.padEnd(10)} ${'Size Δ'}`);
    console.log(`  ${'─'.repeat(55)} ────────── ───────`);
    let totalOriginal = 0;
    let totalNew = 0;
    for (const detail of sanitizedDetails) {
      const sizeDelta = detail.newSize - detail.originalSize;
      const sizeStr = sizeDelta >= 0 ? `+${sizeDelta}` : `${sizeDelta}`;
      console.log(`  ${detail.file.padEnd(55)} ${String(detail.matches).padEnd(10)} ${sizeStr}B`);
      totalOriginal += detail.originalSize;
      totalNew += detail.newSize;
    }
    const totalDelta = totalNew - totalOriginal;
    const totalStr = totalDelta >= 0 ? `+${totalDelta}` : `${totalDelta}`;
    console.log(`  ${'─'.repeat(55)} ────────── ───────`);
    console.log(`  ${'TOTAL'.padEnd(55)} ${String(sanitizedCount).padEnd(10)} ${totalStr}B`);
  }

  console.log('');
  if (DRY_RUN) {
    console.log('  ⚠ DRY-RUN COMPLETE. Run with --force to apply changes.');
  } else {
    console.log('  ✅ SANITIZATION COMPLETE. All changes applied.');
  }
  console.log('='.repeat(70));
}

// ============================================================
// Main
// ============================================================

function main() {
  console.log(`\n  🔐 Sanitize Workspace v1.0.1`);
  console.log(`  Project Root: ${ROOT}\n`);

  resetMemoryBankFiles();
  scanAndSanitizePaths();
  printSummary();
}

main();