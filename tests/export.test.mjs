import test from 'node:test';
import assert from 'node:assert/strict';
import {slideHTML} from '../static/deck.mjs';
test('slide renderer escapes source text and HTML',()=>{
  const html=slideHTML({title:'Project',theme:'ink'},{content:{layout:'content',title:'<script>alert(1)</script>',subtitle:'',bullets:['<img onerror=x>']}},0);
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
});
