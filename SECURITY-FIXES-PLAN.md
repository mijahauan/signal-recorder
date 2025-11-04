# Security Vulnerability Remediation Plan

**Date**: November 3, 2025  
**Priority**: CRITICAL  
**Estimated Effort**: 10-17 hours

---

## Critical Vulnerabilities Identified

| ID | Issue | Severity | CVSS | Impact | Effort |
|----|-------|----------|------|--------|--------|
| SEC-1 | Hardcoded credentials | CRITICAL | 9.8 | Full compromise | 2-4h |
| SEC-2 | Command injection (exec) | HIGH | 8.1 | RCE | 4-6h |
| SEC-3 | Process injection (PID) | HIGH | 7.5 | RCE/DoS | 2-3h |
| SEC-4 | Path traversal | MEDIUM | 6.3 | File write | 1-2h |
| SEC-5 | Unsafe process killing | MEDIUM | 6.5 | DoS | 1-2h |

---

## Phase 1: Critical Fixes (Week 1)

### SEC-1: Replace Hardcoded Authentication ⚠️ CRITICAL

**Current Vulnerability** (`web-ui/simple-server.js:478`):
```javascript
if (username === 'admin' && password === 'admin') {
  res.json({ token: 'admin-token', ... });
}
```

**Fix Implementation**:
1. Install bcrypt, jsonwebtoken, express-rate-limit
2. Create secure password hashing system
3. Generate JWT tokens with expiration
4. Implement rate limiting
5. Create initial setup script

**Files to Modify**:
- `web-ui/simple-server.js` - Authentication endpoints
- `web-ui/package.json` - Add dependencies
- `web-ui/data/users.json` - Secure user storage
- New: `web-ui/scripts/create-admin.js` - Initial setup

**Dependencies**:
```json
{
  "bcrypt": "^5.1.0",
  "jsonwebtoken": "^9.0.0",
  "express-rate-limit": "^6.7.0"
}
```

---

### SEC-2: Fix Command Injection ⚠️ HIGH

**Vulnerable Patterns**:
1. `exec(\`${venvPython} -c "${pythonScript}"\`)` - Line 243
2. `exec(\`ps -p ${statusData.pid}\`)` - Multiple locations

**Fix Strategy**:
- Replace `exec()` with `execFile()` or `spawn()`
- Use array arguments instead of string interpolation
- Validate all inputs before passing to shell

**Example Fix**:
```javascript
// BEFORE (VULNERABLE)
exec(`${venvPython} -c "${pythonScript}"`, ...);

// AFTER (SECURE)
import { execFile } from 'child_process';
execFile(venvPython, ['-c', pythonScript], { timeout: 10000 }, ...);
```

---

### SEC-3: Fix Process Injection ⚠️ HIGH

**Vulnerable Code**:
```javascript
exec(`ps -p ${statusData.pid} -o comm=`);
exec(`kill -9 ${pids[0]}`);
```

**Fix Strategy**:
1. Validate PIDs are integers
2. Use Node.js built-in `process.kill()`
3. Use `execFile()` with array args for ps commands

**Example Fix**:
```javascript
// Validate PID
const pid = parseInt(statusData.pid, 10);
if (isNaN(pid) || pid <= 0) {
  return res.status(400).json({ error: 'Invalid PID' });
}

// Use execFile
execFile('ps', ['-p', pid.toString(), '-o', 'comm='], ...);

// Use Node.js process.kill()
try {
  process.kill(pid, 'SIGTERM');
} catch (err) {
  // Process doesn't exist
}
```

---

### SEC-4: Fix Path Traversal 🟡 MEDIUM

**Vulnerable Code**:
```javascript
const filename = `${installDir}/config/grape-${config.station.callsign}.toml`;
fs.writeFileSync(filename, toml);
```

**Fix Strategy**:
1. Validate callsign format (alphanumeric only)
2. Sanitize input
3. Verify final path is within allowed directory

**Example Fix**:
```javascript
function validateCallsign(callsign) {
  if (!callsign || typeof callsign !== 'string') return false;
  if (callsign.length < 3 || callsign.length > 8) return false;
  return /^[A-Z0-9]+$/i.test(callsign);
}

if (!validateCallsign(config.station.callsign)) {
  return res.status(400).json({ error: 'Invalid callsign format' });
}

const safeCallsign = config.station.callsign.replace(/[^A-Z0-9]/gi, '');
const filename = join(installDir, 'config', `grape-${safeCallsign}.toml`);

// Verify path doesn't escape config directory
const configDir = join(installDir, 'config');
if (!filename.startsWith(configDir)) {
  return res.status(400).json({ error: 'Invalid path' });
}
```

---

## Phase 2: Security Hardening (Week 2)

### Add Security Headers

```bash
cd web-ui
pnpm add helmet cors morgan
```

```javascript
import helmet from 'helmet';
import cors from 'cors';
import morgan from 'morgan';

app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      styleSrc: ["'self'", "'unsafe-inline'"]
    }
  },
  hsts: { maxAge: 31536000 }
}));

app.use(cors({
  origin: process.env.ALLOWED_ORIGINS || 'http://localhost:3000',
  credentials: true
}));

app.use(morgan('combined'));
```

### Input Validation Middleware

Create `web-ui/middleware/validation.js`:
```javascript
export function validateCallsign(callsign) {
  if (!callsign || typeof callsign !== 'string') return false;
  if (callsign.length < 3 || callsign.length > 8) return false;
  return /^[A-Z0-9]+$/i.test(callsign);
}

export function validateSSRC(ssrc) {
  const num = parseInt(ssrc, 10);
  return Number.isInteger(num) && num > 0 && num <= 0xFFFFFFFF;
}

export function validateFrequency(freq) {
  const num = parseFloat(freq);
  return !isNaN(num) && num > 0 && num < 30e6;
}

export function validatePID(pid) {
  const num = parseInt(pid, 10);
  return Number.isInteger(num) && num > 0 && num < 32768;
}
```

### Audit Logging

```bash
pnpm add winston
```

Create `web-ui/utils/audit.js`:
```javascript
import winston from 'winston';

export const auditLogger = winston.createLogger({
  level: 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.json()
  ),
  transports: [
    new winston.transports.File({ 
      filename: '/var/log/signal-recorder/audit.log' 
    })
  ]
});

export function auditLog(event, user, details) {
  auditLogger.info({
    event,
    user: user?.id,
    username: user?.username,
    timestamp: new Date().toISOString(),
    ip: details.ip,
    ...details
  });
}
```

---

## Phase 3: Testing & Documentation (Week 3)

### Security Testing Checklist

- [ ] Test login with invalid credentials (should fail)
- [ ] Test login with > 5 attempts (should rate limit)
- [ ] Test JWT token expiration
- [ ] Test path traversal attempts (should reject)
- [ ] Test command injection attempts (should fail)
- [ ] Test PID validation (should reject invalid PIDs)
- [ ] Verify all subprocess calls use array args
- [ ] Run `npm audit` and fix vulnerabilities
- [ ] Run `snyk test` for security scan
- [ ] Manual penetration testing

### Documentation Updates

- [ ] Update README.md with security best practices
- [ ] Document authentication setup process
- [ ] Create SECURITY.md with vulnerability reporting process
- [ ] Document JWT secret generation
- [ ] Add security section to ARCHITECTURE.md

---

## Implementation Order

### Day 1-2: Critical Fixes
1. ✅ Install security dependencies
2. ✅ Implement bcrypt password hashing
3. ✅ Replace static tokens with JWT
4. ✅ Add rate limiting
5. ✅ Create admin setup script

### Day 3-4: Command Injection Fixes
1. ✅ Replace all `exec()` with `execFile()`
2. ✅ Add PID validation
3. ✅ Use Node.js `process.kill()`
4. ✅ Test all daemon control functions

### Day 5: Path & Input Validation
1. ✅ Add validation middleware
2. ✅ Sanitize callsign input
3. ✅ Add path verification
4. ✅ Test configuration save

### Day 6-7: Security Hardening
1. ✅ Add security headers
2. ✅ Implement audit logging
3. ✅ Add CORS configuration
4. ✅ Review all API endpoints

### Day 8-10: Testing
1. ✅ Security testing
2. ✅ Penetration testing
3. ✅ Documentation updates
4. ✅ Code review

---

## Rollback Plan

If issues arise during implementation:

1. **Git branches**: Create feature branch for each fix
2. **Backup**: Copy current `simple-server.js` to `simple-server.js.backup`
3. **Incremental**: Test each change independently
4. **Revert**: Use `git revert` if a change breaks functionality

---

## Success Criteria

✅ No hardcoded credentials  
✅ All exec() calls replaced with execFile()  
✅ All inputs validated  
✅ JWT authentication working  
✅ Rate limiting active  
✅ Security headers present  
✅ Audit logging functional  
✅ npm audit shows 0 critical vulnerabilities  
✅ All tests passing  

---

## Next Steps

Run this command to start:
```bash
cd /home/mjh/git/signal-recorder/web-ui
pnpm add bcrypt jsonwebtoken express-rate-limit helmet cors winston better-sqlite3
```

Then follow the implementation checklist above.
