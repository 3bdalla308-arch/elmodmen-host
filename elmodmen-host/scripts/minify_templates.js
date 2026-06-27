/*
 * يصغّر ويعمّي بلوك <script> الداخلي في كل قوالب HTML.
 * إعدادات محافظة: ما يغيّرش أسماء الدوال (عشان onclick="..." تفضل شغّالة)
 * ولا يحذف دوال "يظنها" غير مستخدمة.
 * الاستخدام:  node scripts/minify_templates.js <مجلد_القوالب>
 */
const fs = require("fs");
const { minify } = require("terser");

const dir = process.argv[2] || "templates";

(async () => {
	const files = fs.readdirSync(dir).filter((f) => f.endsWith(".html"));
	for (const file of files) {
		const p = dir + "/" + file;
		let html = fs.readFileSync(p, "utf8");
		const m = html.match(/<script>([\s\S]*?)<\/script>/);
		if (!m) {
			console.log("skip (no inline script):", file);
			continue;
		}
		const result = await minify(m[1], {
			compress: { dead_code: false, unused: false, toplevel: false },
			mangle: false,
			format: { comments: false },
		});
		if (result.error) {
			console.error("ERROR in", file, result.error);
			process.exit(1);
		}
		html = html.replace(m[0], "<script>" + result.code + "</script>");
		fs.writeFileSync(p, html);
		console.log("minified:", file);
	}
	console.log("done.");
})();
