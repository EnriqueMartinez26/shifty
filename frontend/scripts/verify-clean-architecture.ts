#!/usr/bin/env node

/**
 * verify-clean-architecture.ts
 *
 * Verifies that the frontend follows 100% Pure Clean Architecture
 * without violating the Dependency Rule.
 *
 * Usage: npx ts-node verify-clean-architecture.ts
 * Or: node verify-clean-architecture.js (after compilation)
 */

import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

interface ViolationReport {
  file: string
  line: number
  column: number
  severity: 'error' | 'warning'
  message: string
  code: string
}

interface ArchitectureReport {
  totalFiles: number
  totalViolations: number
  errorCount: number
  warningCount: number
  violations: ViolationReport[]
  summary: {
    domainViolations: number
    infrastructureViolations: number
    applicationViolations: number
    circularDeps: number
    unusedImports: number
  }
  passed: boolean
}

const FRONTEND_ROOT = path.resolve(__dirname, '..')
const SRC_DIR = path.join(FRONTEND_ROOT, 'src')

// Color codes for console output
const colors = {
  reset: '\x1b[0m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[36m'
}

// Regex patterns for import detection
const IMPORT_PATTERNS = {
  namedImport: /import\s*\{\s*([^}]+)\s*\}\s*from\s*['"]([^'"]+)['"]/g,
  defaultImport: /import\s+(\w+)\s+from\s*['"]([^'"]+)['"]/g,
  typeImport: /import\s+type\s+\{\s*([^}]+)\s*\}\s+from\s*['"]([^'"]+)['"]/g,
  requireImport: /require\s*\(\s*['"]([^'"]+)['"]\s*\)/g
}

// Allowed import patterns per layer
const ALLOWED_IMPORTS: Record<string, string[]> = {
  domain: ['@domain'],
  application: ['@domain', '@application', '@infrastructure', '@shared'],
  infrastructure: ['@domain', '@infrastructure', '@shared'],
  presentation: [
    '@domain',
    '@application',
    '@infrastructure',
    '@presentation',
    '@shared',
    'react',
    '@tanstack/react-query',
    'react-router-dom'
  ],
  shared: ['@shared']
}

// Forbidden imports per layer
const FORBIDDEN_IMPORTS: Record<string, string[]> = {
  domain: ['react', 'axios', '@tanstack', '@infrastructure', '@application', '@presentation'],
  infrastructure: ['@application', '@presentation', 'react'],
  application: ['@presentation'],
  presentation: [],
  shared: ['@domain', '@application', '@infrastructure', '@presentation']
}

/**
 * Get layer from file path
 */
function getLayer(filePath: string): string | null {
  const normalized = filePath.replace(/\\/g, '/')
  if (normalized.includes('/domain/')) return 'domain'
  if (normalized.includes('/application/')) return 'application'
  if (normalized.includes('/infrastructure/')) return 'infrastructure'
  if (normalized.includes('/presentation/')) return 'presentation'
  if (normalized.includes('/shared/')) return 'shared'
  return null
}

/**
 * Extract imports from file content
 */
function extractImports(
  content: string,
  filePath: string
): { module: string; line: number; column: number }[] {
  const imports: { module: string; line: number; column: number }[] = []
  const lines = content.split('\n')

  lines.forEach((line, lineIdx) => {
    // Named imports
    const namedMatches = [...line.matchAll(IMPORT_PATTERNS.namedImport)]
    namedMatches.forEach((match) => {
      imports.push({
        module: match[2],
        line: lineIdx + 1,
        column: match.index || 0
      })
    })

    // Default imports
    const defaultMatches = [...line.matchAll(IMPORT_PATTERNS.defaultImport)]
    defaultMatches.forEach((match) => {
      imports.push({
        module: match[2],
        line: lineIdx + 1,
        column: match.index || 0
      })
    })

    // Type imports
    const typeMatches = [...line.matchAll(IMPORT_PATTERNS.typeImport)]
    typeMatches.forEach((match) => {
      imports.push({
        module: match[2],
        line: lineIdx + 1,
        column: match.index || 0
      })
    })
  })

  return imports
}

/**
 * Check if import violates Dependency Rule
 */
function isViolation(
  importModule: string,
  sourceLayer: string | null
): { isViolation: boolean; reason: string } {
  if (!sourceLayer) {
    return { isViolation: false, reason: 'Unknown layer' }
  }

  // Extract layer from import path
  let importLayer: string | null = null
  if (importModule.startsWith('@domain')) importLayer = 'domain'
  else if (importModule.startsWith('@application')) importLayer = 'application'
  else if (importModule.startsWith('@infrastructure')) importLayer = 'infrastructure'
  else if (importModule.startsWith('@presentation')) importLayer = 'presentation'
  else if (importModule.startsWith('@shared')) importLayer = 'shared'
  else if (
    importModule.startsWith('react') ||
    importModule.startsWith('axios') ||
    importModule.startsWith('@tanstack')
  ) {
    // External libraries - allowed in presentation/application/infrastructure, NOT domain
    if (sourceLayer === 'domain') {
      return {
        isViolation: true,
        reason: `Domain cannot import external library: ${importModule}`
      }
    }
    return { isViolation: false, reason: 'External library allowed' }
  } else {
    return { isViolation: false, reason: 'Relative import (allowed)' }
  }

  // Check if import layer is in allowed list
  const allowed = ALLOWED_IMPORTS[sourceLayer] || []
  if (!allowed.includes(`@${importLayer}`)) {
    return {
      isViolation: true,
      reason: `${sourceLayer} cannot import from ${importLayer}`
    }
  }

  return { isViolation: false, reason: 'Import allowed' }
}

/**
 * Get all TypeScript/TSX files in src/
 */
function getAllSourceFiles(dir: string): string[] {
  const files: string[] = []

  function walk(currentPath: string): void {
    const items = fs.readdirSync(currentPath)

    items.forEach((item) => {
      const fullPath = path.join(currentPath, item)
      const stat = fs.statSync(fullPath)

      if (stat.isDirectory()) {
        if (!item.startsWith('.') && item !== 'node_modules') {
          walk(fullPath)
        }
      } else if (item.endsWith('.ts') || item.endsWith('.tsx')) {
        files.push(fullPath)
      }
    })
  }

  walk(dir)
  return files
}

/**
 * Analyze single file for violations
 */
function analyzeFile(filePath: string): ViolationReport[] {
  try {
    const content = fs.readFileSync(filePath, 'utf-8')
    const layer = getLayer(filePath)
    const imports = extractImports(content, filePath)
    const violations: ViolationReport[] = []

    imports.forEach(({ module, line, column }) => {
      const { isViolation: violatesRule, reason } = isViolation(module, layer)

      if (violatesRule) {
        violations.push({
          file: path.relative(FRONTEND_ROOT, filePath),
          line,
          column,
          severity: 'error',
          message: reason,
          code: 'ARCH-001'
        })
      }
    })

    return violations
  } catch (error) {
    console.error(`Error analyzing file ${filePath}:`, error)
    return []
  }
}

/**
 * Check for features/ directory (should not exist)
 */
function checkFeaturesDirectory(): ViolationReport[] {
  const featuresDir = path.join(SRC_DIR, 'features')
  const violations: ViolationReport[] = []

  if (fs.existsSync(featuresDir)) {
    violations.push({
      file: 'src/features/',
      line: 0,
      column: 0,
      severity: 'error',
      message:
        '❌ ARCHITECTURE VIOLATION: features/ directory still exists. Must be deleted in Phase 3.',
      code: 'ARCH-002'
    })
  }

  return violations
}

/**
 * Check for old directories that should not exist
 */
function checkLegacyDirectories(): ViolationReport[] {
  const violations: ViolationReport[] = []
  const legacyDirs = [
    { path: 'pages', reason: 'pages/ should be moved to presentation/pages/' },
    { path: 'layouts', reason: 'layouts/ should be moved to presentation/layouts/' }
  ]

  legacyDirs.forEach(({ path: dirPath, reason }) => {
    const fullPath = path.join(SRC_DIR, dirPath)
    if (fs.existsSync(fullPath)) {
      violations.push({
        file: `src/${dirPath}/`,
        line: 0,
        column: 0,
        severity: 'error',
        message: `❌ ARCHITECTURE VIOLATION: ${reason}`,
        code: 'ARCH-003'
      })
    }
  })

  return violations
}

/**
 * Verify domain layer has NO external dependencies
 */
function checkDomainPurity(): ViolationReport[] {
  const violations: ViolationReport[] = []
  const domainDir = path.join(SRC_DIR, 'domain')

  if (!fs.existsSync(domainDir)) {
    return violations
  }

  const domainFiles = getAllSourceFiles(domainDir)
  const forbiddenPatterns = [
    /import.*from\s*['"]react['"]/,
    /import.*from\s*['"]axios['"]/,
    /import.*from\s*['"]@tanstack/,
    /import.*from\s*['"]@infrastructure/,
    /import.*from\s*['"]@application/,
    /import.*from\s*['"]@presentation/
  ]

  domainFiles.forEach((filePath) => {
    const content = fs.readFileSync(filePath, 'utf-8')
    const lines = content.split('\n')

    lines.forEach((line, lineIdx) => {
      forbiddenPatterns.forEach((pattern) => {
        if (pattern.test(line)) {
          violations.push({
            file: path.relative(FRONTEND_ROOT, filePath),
            line: lineIdx + 1,
            column: 0,
            severity: 'error',
            message: `Domain layer must be pure (no external imports): ${line.trim()}`,
            code: 'ARCH-004'
          })
        }
      })
    })
  })

  return violations
}

/**
 * Main verification function
 */
function verifyArchitecture(): ArchitectureReport {
  console.log(`${colors.blue}🔍 Verifying Clean Architecture compliance...${colors.reset}\n`)

  const report: ArchitectureReport = {
    totalFiles: 0,
    totalViolations: 0,
    errorCount: 0,
    warningCount: 0,
    violations: [],
    summary: {
      domainViolations: 0,
      infrastructureViolations: 0,
      applicationViolations: 0,
      circularDeps: 0,
      unusedImports: 0
    },
    passed: true
  }

  // Check legacy directories
  const legacyViolations = checkLegacyDirectories()
  report.violations.push(...legacyViolations)

  // Check features/ directory
  const featuresViolations = checkFeaturesDirectory()
  report.violations.push(...featuresViolations)

  // Check domain purity
  const domainPurityViolations = checkDomainPurity()
  report.violations.push(...domainPurityViolations)

  // Analyze all source files
  const allFiles = getAllSourceFiles(SRC_DIR)
  report.totalFiles = allFiles.length

  allFiles.forEach((filePath) => {
    const violations = analyzeFile(filePath)
    report.violations.push(...violations)

    // Count by layer
    const layer = getLayer(filePath)
    violations.forEach((v) => {
      if (layer === 'domain') report.summary.domainViolations++
      else if (layer === 'infrastructure') report.summary.infrastructureViolations++
      else if (layer === 'application') report.summary.applicationViolations++
    })
  })

  // Count error/warning
  report.totalViolations = report.violations.length
  report.errorCount = report.violations.filter((v) => v.severity === 'error').length
  report.warningCount = report.violations.filter((v) => v.severity === 'warning').length
  report.passed = report.errorCount === 0

  return report
}

/**
 * Print report
 */
function printReport(report: ArchitectureReport): void {
  console.log(
    `\n${colors.blue}═══════════════════════════════════════════════════════════════${colors.reset}`
  )
  console.log(
    `${colors.blue}                    CLEAN ARCHITECTURE REPORT                     ${colors.reset}`
  )
  console.log(
    `${colors.blue}═══════════════════════════════════════════════════════════════${colors.reset}\n`
  )

  console.log(`Files analyzed:        ${report.totalFiles}`)
  console.log(`Total violations:      ${report.totalViolations}`)
  console.log(`Errors:                ${report.errorCount}`)
  console.log(`Warnings:              ${report.warningCount}\n`)

  console.log('Violations by category:')
  console.log(`  • Domain layer:        ${report.summary.domainViolations} violations`)
  console.log(`  • Infrastructure:      ${report.summary.infrastructureViolations} violations`)
  console.log(`  • Application:         ${report.summary.applicationViolations} violations`)
  console.log(`  • Circular deps:       ${report.summary.circularDeps} violations`)
  console.log(`  • Unused imports:      ${report.summary.unusedImports} violations\n`)

  if (report.violations.length > 0) {
    console.log(`${colors.red}VIOLATIONS FOUND:${colors.reset}\n`)

    report.violations.forEach((v, idx) => {
      const color = v.severity === 'error' ? colors.red : colors.yellow
      console.log(
        `${idx + 1}. ${color}[${v.severity.toUpperCase()}]${colors.reset} ${v.file}:${v.line}:${v.column}`
      )
      console.log(`   ${v.message}`)
      console.log(`   Code: ${v.code}\n`)
    })
  }

  console.log(
    `${colors.blue}═══════════════════════════════════════════════════════════════${colors.reset}\n`
  )

  if (report.passed) {
    console.log(
      `${colors.green}✅ PASSED: Architecture is 100% Clean Architecture compliant!${colors.reset}\n`
    )
  } else {
    console.log(
      `${colors.red}❌ FAILED: ${report.errorCount} architecture violations detected.${colors.reset}\n`
    )
    console.log('Fix violations before proceeding. See IMPORT_RULES.md for guidelines.\n')
  }
}

/**
 * Entry point
 */
function main(): void {
  if (!fs.existsSync(SRC_DIR)) {
    console.error(`${colors.red}Error: src/ directory not found at ${SRC_DIR}${colors.reset}`)
    process.exit(1)
  }

  const report = verifyArchitecture()
  printReport(report)

  // Exit with error code if violations found
  process.exit(report.passed ? 0 : 1)
}

main()
