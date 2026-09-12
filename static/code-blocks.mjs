const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const keywords=new Set('def class return if elif else for while in import from as with try except finally raise pass yield lambda self None True False and or not async await int float double char void bool auto const static public private protected virtual override struct enum namespace using std new delete include define return switch case break continue do sizeof null true false function let var export SELECT FROM WHERE JOIN ORDER BY GROUP INSERT UPDATE'.split(' '));
export function codeHTML(text,language='text'){
  // Display-only lexer: no eval, no language runtime, no generated HTML is trusted.
  const pattern=language==='python'?/(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*\b)/g:
    /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*\b)/g;
  let out='',end=0;
  for(const match of String(text).matchAll(pattern)){
    out+=escape(text.slice(end,match.index));const value=match[0];
    const kind=/^(#|\/\/|\/\*)/.test(value)?'comment':/^['"]/.test(value)?'string':/^\d/.test(value)?'number':keywords.has(value)?'keyword':'';
    out+=kind?'<span class="syntax-'+kind+'">'+escape(value)+'</span>':escape(value);end=match.index+value.length;
  }
  return out+escape(text.slice(end));
}
export const codeCSS='.slide-frame .prose-box.kind-code{background:#111d35!important;color:#e9efff!important;border:1px solid #516483!important;border-radius:14px!important;box-shadow:0 10px 25px #0002!important;gap:10px!important}.slide-frame .kind-code h2{color:#e9efff!important;font-family:Consolas,monospace!important;font-size:19px!important}.slide-frame .kind-code p{font:17px/1.4 Consolas,monospace!important;white-space:pre!important;tab-size:4;overflow-wrap:normal!important}.slide-frame .kind-code .prose-source{color:#b8c7e9!important}.kind-code .syntax-keyword{color:#c8a5ff;font-weight:bold}.kind-code .syntax-string{color:#b5e99c}.kind-code .syntax-number{color:#ffd38c}.kind-code .syntax-comment{color:#97aacc;font-style:italic}';
