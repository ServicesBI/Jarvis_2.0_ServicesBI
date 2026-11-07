import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';
import puppeteer from 'puppeteer';

const publicRoot = join(process.cwd(), 'public');
let browser;
let page;
let server;
let origin;

function contentType(pathname) {
  return {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.glb': 'model/gltf-binary',
  }[extname(pathname)] || 'application/octet-stream';
}

async function voiceStatus() {
  return page.$eval('#jarvis-core-voice-status', element => element.textContent);
}

async function waitForVoiceStatus(expected) {
  await page.waitForFunction(
    value => document.getElementById('jarvis-core-voice-status')?.textContent === value,
    {},
    expected,
  );
}

async function clickMic() {
  await page.$eval('#mic-btn', element => element.click());
}

async function startConnectedAttempt() {
  const previousCount = await page.evaluate(() => window.__voiceTest.peers.length);
  await clickMic();
  await waitForVoiceStatus('CONECTANDO');
  await page.waitForFunction(count => window.__voiceTest.peers.length === count + 1, {}, previousCount);
  await page.evaluate(() => window.__voiceTest.peers.at(-1).finishNegotiation());
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(await voiceStatus(), 'CONECTANDO', 'OUVINDO nao pode anteceder um evento real de conexao');
  await page.evaluate(() => {
    const peer = window.__voiceTest.peers.at(-1);
    peer.connect();
    peer.dataChannel.open();
  });
  await waitForVoiceStatus('OUVINDO');
}

before(async () => {
  server = createServer(async (request, response) => {
    try {
      const requestedPath = request.url === '/' ? 'index.html' : request.url.split('?', 1)[0].replace(/^\//, '');
      const pathname = normalize(join(publicRoot, requestedPath));
      if (!pathname.startsWith(publicRoot)) throw new Error('invalid path');
      response.writeHead(200, { 'Content-Type': contentType(pathname) });
      response.end(await readFile(pathname));
    } catch {
      response.writeHead(404);
      response.end('not found');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;

  browser = await puppeteer.launch({ headless: true });
  page = await browser.newPage();
  await page.evaluateOnNewDocument(() => {
    const state = {
      holdSession: false,
      sessionRequestsInFlight: 0,
      maxSessionRequestsInFlight: 0,
      fetches: [],
      peers: [],
      streams: [],
    };
    window.__voiceTest = state;

    class FakeTrack extends EventTarget {
      stopped = false;
      stop() { this.stopped = true; }
      end() { this.dispatchEvent(new Event('ended')); }
    }

    class FakeStream {
      constructor() { this.track = new FakeTrack(); }
      getTracks() { return [this.track]; }
    }

    class FakeDataChannel extends EventTarget {
      readyState = 'connecting';
      closed = false;
      open() {
        if (this.closed) return;
        this.readyState = 'open';
        this.dispatchEvent(new Event('open'));
      }
      send() {}
      close() {
        this.closed = true;
        this.readyState = 'closed';
      }
      message(payload) {
        this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(payload) }));
      }
      fail() { this.dispatchEvent(new Event('error')); }
    }

    class FakePeerConnection extends EventTarget {
      connectionState = 'new';
      iceConnectionState = 'new';
      closed = false;
      dataChannel = null;
      constructor() {
        this.remoteDescriptionPromise = new Promise(resolve => { this.resolveRemoteDescription = resolve; });
        state.peers.push(this);
      }
      addTrack() {}
      createDataChannel() {
        this.dataChannel = new FakeDataChannel();
        return this.dataChannel;
      }
      async createOffer() { return { type: 'offer', sdp: 'test-offer' }; }
      async setLocalDescription() {}
      async setRemoteDescription() { await this.remoteDescriptionPromise; }
      finishNegotiation() { this.resolveRemoteDescription(); }
      connect() {
        this.connectionState = 'connected';
        this.iceConnectionState = 'connected';
        this.dispatchEvent(new Event('connectionstatechange'));
        this.dispatchEvent(new Event('iceconnectionstatechange'));
      }
      fail() {
        this.connectionState = 'failed';
        this.dispatchEvent(new Event('connectionstatechange'));
      }
      close() {
        this.closed = true;
        this.connectionState = 'closed';
      }
    }

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        async getUserMedia() {
          const stream = new FakeStream();
          state.streams.push(stream);
          return stream;
        },
      },
    });
    window.RTCPeerConnection = FakePeerConnection;

    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input, options = {}) => {
      const url = String(input);
      if (url === '/api/realtime/session') {
        const record = { url, aborted: false };
        state.fetches.push(record);
        state.sessionRequestsInFlight += 1;
        state.maxSessionRequestsInFlight = Math.max(state.maxSessionRequestsInFlight, state.sessionRequestsInFlight);
        const finish = () => { state.sessionRequestsInFlight = Math.max(0, state.sessionRequestsInFlight - 1); };
        if (state.holdSession) {
          return new Promise((resolve, reject) => {
            options.signal?.addEventListener('abort', () => {
              record.aborted = true;
              finish();
              reject(new DOMException('Aborted', 'AbortError'));
            }, { once: true });
          });
        }
        options.signal?.addEventListener('abort', () => { record.aborted = true; }, { once: true });
        finish();
        return new Response(JSON.stringify({ value: 'test-token' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url === 'https://api.openai.com/v1/realtime/calls') {
        const record = { url, aborted: false };
        state.fetches.push(record);
        options.signal?.addEventListener('abort', () => { record.aborted = true; }, { once: true });
        return new Response('test-answer', { status: 200 });
      }
      return nativeFetch(input, options);
    };
  });
  await page.setRequestInterception(true);
  page.on('request', request => request.url().startsWith(origin) ? request.continue() : request.abort());
  await page.goto(origin, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.setVoiceStatus === 'function');
});

after(async () => {
  await browser?.close();
  await new Promise(resolve => server?.close(resolve));
});

test('estado inicial e cancelamento durante CONECTANDO ficam em MUTE sem sessao duplicada', async () => {
  assert.equal(await voiceStatus(), 'MUTE');
  assert.equal(
    await page.$eval('#jarvis-core-voice-status', element => getComputedStyle(element).color),
    'rgb(255, 123, 134)',
  );

  await page.evaluate(() => { window.__voiceTest.holdSession = true; });
  await clickMic();
  await waitForVoiceStatus('CONECTANDO');
  await page.waitForFunction(() => window.__voiceTest.sessionRequestsInFlight === 1);
  await clickMic();
  await waitForVoiceStatus('MUTE');
  await page.waitForFunction(() => window.__voiceTest.sessionRequestsInFlight === 0);

  const cancelled = await page.evaluate(() => ({
    aborted: window.__voiceTest.fetches[0].aborted,
    stopped: window.__voiceTest.streams[0].track.stopped,
    peers: window.__voiceTest.peers.length,
    maximum: window.__voiceTest.maxSessionRequestsInFlight,
  }));
  assert.deepEqual(cancelled, { aborted: true, stopped: true, peers: 0, maximum: 1 });

  await page.evaluate(() => { window.__voiceTest.holdSession = false; });
  await startConnectedAttempt();
  assert.equal(
    await page.$eval('#jarvis-core-voice-status', element => getComputedStyle(element).color),
    'rgb(57, 255, 136)',
  );
});

test('eventos reais dirigem o ciclo e callbacks antigos nao saem de MUTE', async () => {
  const activePeerIndex = await page.evaluate(() => window.__voiceTest.peers.length - 1);
  await page.evaluate(index => {
    const channel = window.__voiceTest.peers[index].dataChannel;
    channel.message({ type: 'input_audio_buffer.speech_stopped' });
  }, activePeerIndex);
  await waitForVoiceStatus('PENSANDO');

  await page.evaluate(index => {
    window.__voiceTest.peers[index].dataChannel.message({ type: 'response.output_audio.delta' });
  }, activePeerIndex);
  await waitForVoiceStatus('FALANDO');
  assert.equal(await page.$eval('.avatar-container', element => element.classList.contains('speaking')), true);

  await page.evaluate(index => {
    window.__voiceTest.peers[index].dataChannel.message({ type: 'response.output_audio.done' });
  }, activePeerIndex);
  await waitForVoiceStatus('OUVINDO');

  await clickMic();
  await waitForVoiceStatus('MUTE');
  await page.evaluate(index => {
    window.__voiceTest.peers[index].dataChannel.message({ type: 'response.output_audio.delta' });
  }, activePeerIndex);
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(await voiceStatus(), 'MUTE');

  await startConnectedAttempt();
  await page.evaluate(() => window.__voiceTest.streams.at(-1).track.end());
  await waitForVoiceStatus('MUTE');

  await startConnectedAttempt();
  await page.evaluate(() => {
    window.__voiceTest.peers.at(-1).dataChannel.message({ type: 'error', error: { code: 'session_failed' } });
  });
  await waitForVoiceStatus('MUTE');

  await startConnectedAttempt();
  await page.evaluate(() => window.__voiceTest.peers.at(-1).fail());
  await waitForVoiceStatus('MUTE');
});
