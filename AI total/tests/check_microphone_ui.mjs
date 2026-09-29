import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const { chromium } = createRequire(import.meta.url)('playwright');
const python = process.env.AI_TEST_PYTHON || 'python';
const server = spawn(python, ['-u', '-c', 'from voice import capture; print("RESULT="+capture(timeout=45, open_browser=False), flush=True)'], { env: { ...process.env, PYTHONUTF8: '1' } });
let output = '', errors = '';
server.stdout.on('data', chunk => output += chunk.toString('utf8'));
server.stderr.on('data', chunk => errors += chunk.toString('utf8'));
const exited = once(server, 'exit');
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
    for (let i=0; i<100 && !output.includes('http://'); i++) await new Promise(r=>setTimeout(r,50));
    const url = output.match(/http:\/\/127\.0\.0\.1:\d+\/[^\s]+/)?.[0];
    assert.ok(url, errors || 'Voice bridge did not start');
    const page = await browser.newPage({ viewport: { width: 1000, height: 850 } });
    await page.addInitScript(() => {
        window.testTracks = 0;
        navigator.mediaDevices.getUserMedia = async () => ({ getTracks: () => [{ stop: () => testTracks++ }] });
        window.SpeechRecognition = class {
            start() { this.onresult({ results: [[{ transcript: 'Внутри кто-нибудь есть?' }]] }); this.onend(); }
            abort() {} stop() { this.onend?.(); }
        };
    });
    await page.goto(url);
    await page.locator('#start').click();
    await page.waitForFunction(() => document.querySelector('#text').value.includes('Внутри'));
    assert.equal(await page.evaluate(() => testTracks), 1);
    await page.locator('#text').fill('Внутри остались люди?');
    await fs.mkdir('test-output', { recursive: true });
    await page.screenshot({ path: 'test-output/microphone.png' });
    await page.locator('#send').click();
    await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('Передано.'));
    await exited;
    assert.ok(output.includes('RESULT=Внутри остались люди?'), output + errors);
    console.log('Voice UI: permission request, transcript correction and confirmed delivery passed (speech engine mocked).');
} finally {
    server.kill(); await browser.close();
}
