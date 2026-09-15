<!-- ABOUTME: 后端最小运行说明，指向契约真相源与常用验证命令。 -->
<!-- ABOUTME: 本文件不承载 schema 设计；数据契约以 docs/schema-contract.md 为准。 -->

# Backend

```bash
cd backend
uv sync
cp .env.example .env            # 本机 Supabase 栈参数与模型 API key
supabase start                  # 在仓库根目录；持久化用例需要 127.0.0.1:54322
uv run pytest
uv run uvicorn sustainability_desk.api.app:app --reload
```

环境变量以 `.env.example` 为准；`.env` 不入库。Word 导出的视觉验收用例需要 LibreOffice（`soffice`）。
模型登记在 `src/sustainability_desk/llm/model_registry.py`：生成默认走 Azure OpenAI 的 luna 部署，judge 走同资源异部署的 terra；其他已登记模型为可选候选，配好对应密钥即可选用。密钥只经环境变量注入。

数据契约真相源：`docs/schema-contract.md`。

主要实现入口：
- API：`backend/src/sustainability_desk/api/app.py`
- 导出：`backend/src/sustainability_desk/export/docx_renderer.py`
- 生成上下文：`backend/src/sustainability_desk/llm/`
- 结构化数据：`backend/data/`
