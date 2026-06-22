import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from http.server import SimpleHTTPRequestHandler, HTTPServer

TEXT_EXTS = {'.md', '.json', '.html', '.css', '.js', '.csv', '.txt', '.xml', '.svg'}

WRAP_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{max-width:860px;margin:32px auto;padding:0 20px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.7;color:#1e1e1e;background:#fff}
  pre{background:#f5f5f5;padding:14px;border-radius:6px;overflow-x:auto;white-space:pre-wrap}
  code{background:#f0f0f0;padding:1px 5px;border-radius:4px}
  h1,h2{line-height:1.3}
</style>
</head>
<body>
<pre>
%s
</pre>
</body>
</html>"""

class UTF8Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.md': 'text/html'}

    def guess_type(self, path):
        mime = super().guess_type(path)
        lower = path.lower()
        if mime.startswith('text/') or any(lower.endswith(e) for e in TEXT_EXTS):
            return mime + '; charset=utf-8'
        return mime

    def do_GET(self):
        if self.path.endswith('.md'):
            try:
                filepath = self.translate_path(self.path)
                content = open(filepath, 'r', encoding='utf-8').read()
                html = WRAP_HTML % content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                data = html.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self.send_error(404, 'File not found')
            return
        super().do_GET()

    def log_message(self, format, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), args[0]))

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
print(f"Serving at http://localhost:{port} (UTF-8)")
HTTPServer(('', port), UTF8Handler).serve_forever()
