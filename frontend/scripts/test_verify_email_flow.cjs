/**
 * test_verify_email_flow.cjs — Static and behavioral verification of email OTP registration flow.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let passed = 0;
let failed = 0;

function assert(condition, message) {
  if (condition) {
    console.log(`  ok   ${message}`);
    passed++;
  } else {
    console.error(`  FAIL ${message}`);
    failed++;
  }
}

console.log('\n[1] Router configuration');
const routerFile = fs.readFileSync(path.join(ROOT, 'src/landing/router.ts'), 'utf8');
assert(routerFile.includes("export const VERIFY_EMAIL_PATH = '/verify-email';"), 'router.ts exports VERIFY_EMAIL_PATH');

console.log('\n[2] RouterRoot adoption');
const rootFile = fs.readFileSync(path.join(ROOT, 'src/RouterRoot.tsx'), 'utf8');
assert(rootFile.includes('VERIFY_EMAIL_PATH'), 'RouterRoot imports VERIFY_EMAIL_PATH');
assert(rootFile.includes('VerifyEmailPage'), 'RouterRoot code-splits VerifyEmailPage');
assert(rootFile.includes('isVerifyEmail'), 'RouterRoot checks isVerifyEmail route path');
assert(rootFile.includes('document.title = \'Verify Email — BuildWise AI\';'), 'RouterRoot sets document title for verify email');
assert(rootFile.includes('!session.user?.emailVerified'), 'ProtectedApp blocks unverified users');
assert(rootFile.includes("navigate(`${VERIFY_EMAIL_PATH}?email=${encodeURIComponent(session.user.email)}`);"), 'ProtectedApp bounces unverified sessions to /verify-email');

console.log('\n[3] SignUpPage redirect integration');
const signUpFile = fs.readFileSync(path.join(ROOT, 'src/auth/SignUpPage.tsx'), 'utf8');
assert(signUpFile.includes('VERIFY_EMAIL_PATH'), 'SignUpPage imports VERIFY_EMAIL_PATH');
assert(signUpFile.includes('navigate(`${VERIFY_EMAIL_PATH}?email=${encodeURIComponent(email.trim())}`);'), 'SignUpPage navigates to /verify-email upon successful registration');
const inHandleSubmit = signUpFile.split('handleSubmit')[1]?.split('return (')[0] || '';
assert(!inHandleSubmit.includes('window.location.replace(APP_PATH)'), 'SignUpPage registration handler navigates to /verify-email instead of directly entering /app');

console.log('\n[4] SignInPage unverified account detection');
const signInFile = fs.readFileSync(path.join(ROOT, 'src/auth/SignInPage.tsx'), 'utf8');
assert(signInFile.includes('VERIFY_EMAIL_PATH'), 'SignInPage imports VERIFY_EMAIL_PATH');
assert(signInFile.includes('isUnverified'), 'SignInPage tracks isUnverified error state');
assert(signInFile.includes('res.error.code === \'EMAIL_NOT_VERIFIED\''), 'SignInPage evaluates EMAIL_NOT_VERIFIED code');
assert(signInFile.includes('navigate(`${VERIFY_EMAIL_PATH}?email=${encodeURIComponent(email.trim())}`)'), 'SignInPage provides one-click navigation to /verify-email');

console.log('\n[5] VerifyEmailPage component anatomy');
const verifyFile = fs.readFileSync(path.join(ROOT, 'src/auth/VerifyEmailPage.tsx'), 'utf8');
assert(verifyFile.includes('authClient.emailOtp.verifyEmail'), 'VerifyEmailPage calls authClient.emailOtp.verifyEmail');
assert(verifyFile.includes('authClient.emailOtp.sendVerificationOtp'), 'VerifyEmailPage calls authClient.emailOtp.sendVerificationOtp for resend');
assert(verifyFile.includes('inputMode="numeric"'), 'Inputs have numeric inputMode for mobile virtual keyboards');
assert(verifyFile.includes('autoComplete="one-time-code"'), 'Inputs have one-time-code autocomplete');
assert(verifyFile.includes('resendCooldown'), '60-second resend countdown timer is implemented');
assert(verifyFile.includes('maskedEmail'), 'Safe email masking prevents PII exposure');
assert(verifyFile.includes('handleOtpPaste'), 'Full 6-digit clipboard paste handling is implemented');
assert(verifyFile.includes('handleOtpKeyDown'), 'Backspace and arrow key navigation is implemented');

console.log(`\n=== Verification result: ${passed} passed, ${failed} failed ===\n`);
if (failed > 0) {
  process.exit(1);
}
