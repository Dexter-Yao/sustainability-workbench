# 晉澧精密 · 合成企業 corpus（港交所知識包）

面向港交所《環境、社會及管治報告守則》（《主板上市規則》附錄 C2）報告樣本與本機端到端演練的
**全合成**企業資料。無真實主體、無真實企業數據，因此納入版本控制；真實企業資料一律不入庫。

- 結構與 `../shengyuan/` 同構：走**上傳文件**路徑（`primaryInputMode = materials`），層面引導問題只填
  少量結構化判斷，其餘留空
- 兩個知識包共用同一套事實：`jinli_report_inputs.zh-Hant.yaml` 綁定 `hkex_zh_hant@1`，
  `jinli_report_inputs.en.yaml` 綁定 `hkex_en@1`（英文報告消費繁體資料，是港企實況而非缺陷）
- 不走統一填報工作簿：結構化輸入由 `build_run_fixtures.py` 直接編成 inputWrites 與評分表

## 目錄

| 路徑 | 內容 |
|---|---|
| `materials/` | 語義資料源文（Markdown，繁體中文），版本控制的可讀真相 |
| `materials_docx/` | 由源文轉出的 docx，**上傳用**（派生產物） |
| `build_materials.py` | Markdown → docx（pandoc） |
| `build_run_fixtures.py` | 生成實驗 CLI 的報告輸入 recipe 與資料 selection manifest（指紋與 sha256 現算） |
| `jinli_report_inputs.zh-Hant.yaml` / `.en.yaml` | `sustainability_desk.local_e2e_report_input_fixture.v1` |
| `jinli_materials.yaml` | `sustainability_desk.local_e2e_selection_manifest.v3` |

```bash
cd backend
uv run python tests/fixtures/local_e2e/jinli/build_materials.py
uv run python tests/fixtures/local_e2e/jinli/build_run_fixtures.py
cd .. && ./scripts/dev/local-acceptance-stack.sh up
```

起棧後開啟 <http://localhost:3000>：建報時選 `hkex_zh_hant@1`（英文樣本選 `hkex_en@1`，
同一批繁體資料）→ 按本文事實基準填寫 → 上傳 `materials_docx/` 的資料 → 生成 → 匯出 Word。

無頭校驗走 `tests/test_local_e2e_fixture_corpora.py`：它拿本語料跑通產品自身的輸入鏈路
並渲染出 Word，不呼叫模型。
