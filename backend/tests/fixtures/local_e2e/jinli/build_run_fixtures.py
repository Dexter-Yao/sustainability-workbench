# ABOUTME(en): Builds the experiment CLI inputs of the Jinli corpus: one report-input recipe per HKEX knowledge
# ABOUTME(en): package language and the shared material selection manifest; fingerprints and sha256 are computed.
"""Generate the fixtures the experiment CLI consumes for the Jinli synthetic corpus.

- ``jinli_report_inputs.<language>.yaml`` — ``sustainability_desk.local_e2e_report_input_fixture.v1``: basics,
  board statement and governance texts, structured Aspect judgements and KPI values as inputWrites, with
  ``expected_definition_fingerprint`` computed by ``LightweightReportInputAdapter`` of that package.
- ``jinli_materials.yaml`` — ``sustainability_desk.local_e2e_selection_manifest.v3``: the docx corpus with
  sizes and sha256 computed from the files.

Every number and name comes from README.md "事實基準"; this script must not introduce new facts.

Usage (inside backend/):
    uv run python tests/fixtures/local_e2e/jinli/build_run_fixtures.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from sustainability_desk.contract.report_profiles import knowledge_package_for_profile
from sustainability_desk.material.input_adapter import LightweightReportInputAdapter

FIXTURE_DIR = Path(__file__).resolve().parent
DOCX_DIR = FIXTURE_DIR / "materials_docx"
REPO_ROOT = FIXTURE_DIR.parents[4]
MANIFEST_ID = "jinli-synthetic-corpus"
REPORTING_YEAR = 2025

# Materiality scores by topic id (same values as the package sample_values.yaml): threshold 4.0 on both axes
# yields 8 highly material Aspects, 3 stakeholder-material, 5 of general concern.
SCORES: dict[str, tuple[float, float]] = {
    "climate_change": (4.4, 4.3),
    "emissions": (4.1, 4.4),
    "waste_management": (3.6, 4.2),
    "energy_management": (4.5, 4.1),
    "water_management": (3.2, 3.8),
    "materials_and_packaging": (3.5, 3.6),
    "environment_and_natural_resources": (3.0, 3.7),
    "employment": (4.2, 4.3),
    "health_and_safety": (4.3, 4.6),
    "development_and_training": (3.8, 4.0),
    "labour_standards": (3.4, 4.2),
    "supply_chain_management": (4.2, 4.0),
    "product_responsibility": (4.6, 4.2),
    "data_protection_and_privacy": (3.9, 3.7),
    "anti_corruption": (4.1, 4.2),
    "community_investment": (3.0, 3.9),
}

# KPI key -> (value, note). Auto-summed catalog entries (climate_ghg_scope1_2_total, energy_total) are not written.
METRICS: dict[str, tuple[object, str]] = {
    "economic_revenue": (486.2, "2025 年度綜合收入"),
    "economic_total_employees": (612, "2025 年 12 月 31 日在冊僱員"),
    "climate_ghg_scope1": (1240, "天然氣退火及熱處理爐 968、柴油 109、汽油 80、石油氣 19、製冷劑逸散 64"),
    "climate_ghg_scope2": (6830, "外購電力 11,920 MWh × 0.5730 tCO₂e/MWh（地點法）"),
    "climate_ghg_intensity_revenue": (16.6, "範圍 1+2 合計 8,070 ÷ 營業收入 486.2 百萬港元"),
    "climate_capital_deployment": (3.2, "空壓機及冷卻塔節能改造資本開支"),
    "emissions_nox": (1860, "熱處理爐 1,555（監測）、車輛 305（因子法）"),
    "emissions_sox": (12, "柴油及汽油含硫量計算"),
    "emissions_pm": (96, "熱處理爐 60（監測）、車輛 36（因子法）"),
    "emissions_voc": (340, "清洗及脫脂工序 290（物料衡算）、車輛 50"),
    "emissions_wastewater_discharge": (41200, "東莞廠排放口流量計"),
    "emissions_cod": (1650, "季度第三方檢測平均濃度 40 mg/L × 排放量"),
    "waste_hazardous_total": (36.5, "轉移聯單重量合計"),
    "waste_hazardous_intensity": (0.075, "36.5 噸 ÷ 486.2 百萬港元"),
    "waste_non_hazardous_total": (412, "回收商及環衛過磅單合計"),
    "waste_non_hazardous_intensity": (0.847, "412 噸 ÷ 486.2 百萬港元"),
    "waste_recycled_total": (268, "金屬 232、紙 28、塑膠 8"),
    "waste_recycling_rate": (59.8, "268 ÷ (36.5 + 412)"),
    "energy_purchased_electricity": (11920, "東莞廠 11,690、香港辦公室 230"),
    "energy_renewable_electricity": (1360, "屋頂光伏自發自用；上網 120 MWh 不計入"),
    "energy_natural_gas": (4800, "退火及熱處理爐"),
    "energy_diesel": (410, "備用發電機、廠區貨車"),
    "energy_petrol": (320, "公司車輛"),
    "energy_lpg": (85, "員工飯堂、叉車"),
    "energy_intensity_revenue": (38.9, "能源總量 18,895 MWh ÷ 486.2 百萬港元"),
    "water_consumption_total": (58400, "東莞廠 56,900（水錶）、香港辦公室 1,500（物業分攤估算）"),
    "water_intensity_revenue": (120.1, "58,400 ÷ 486.2 百萬港元"),
    "water_recycled": (6200, "雨水收集 2,400、中水回用 3,800"),
    "packaging_total": (186, "紙箱 124、塑膠托盤及膠袋 47、其他 15"),
    "packaging_recycled_content_rate": (62, "按供應商再生材料含量聲明加權"),
    "employment_total_workforce": (612, "期末在冊"),
    "employment_female": (268, ""),
    "employment_male": (344, ""),
    "employment_full_time": (598, ""),
    "employment_part_time": (14, "香港辦公室行政及清潔崗位"),
    "employment_age_under_30": (214, ""),
    "employment_age_30_50": (336, ""),
    "employment_age_over_50": (62, ""),
    "employment_region_hong_kong": (38, ""),
    "employment_region_mainland": (574, ""),
    "employment_region_other": (0, ""),
    "employment_turnover_rate_total": (11.1, "離職 68 ÷ 期末 612"),
    "employment_turnover_rate_female": (12.3, "33 ÷ 268"),
    "employment_turnover_rate_male": (10.2, "35 ÷ 344"),
    "employment_turnover_rate_under_30": (15.0, "32 ÷ 214"),
    "employment_turnover_rate_30_50": (9.2, "31 ÷ 336"),
    "employment_turnover_rate_over_50": (8.1, "5 ÷ 62"),
    "health_safety_fatalities_current": (0, ""),
    "health_safety_fatalities_prior_1": (0, "2024 年"),
    "health_safety_fatalities_prior_2": (0, "2023 年"),
    "health_safety_fatality_rate": (0, ""),
    "health_safety_lost_days": (126, "7 宗工傷個案合計"),
    "health_safety_injury_cases": (7, "損失工作日 1 天或以上"),
    "training_employees_trained_rate": (91, "557 ÷ 612"),
    "training_rate_female": (90, "241 ÷ 268"),
    "training_rate_male": (92, "316 ÷ 344"),
    "training_rate_senior_management": (100, "12 ÷ 12"),
    "training_rate_middle_management": (95, "55 ÷ 58"),
    "training_rate_general_staff": (90, "490 ÷ 542"),
    "training_hours_average": (18.5, "總時數 11,322 ÷ 612"),
    "training_hours_female": (17.2, "4,614 ÷ 268"),
    "training_hours_male": (19.5, "6,708 ÷ 344"),
    "training_hours_senior_management": (24.0, "288 ÷ 12"),
    "training_hours_middle_management": (22.5, "1,305 ÷ 58"),
    "training_hours_general_staff": (18.0, "9,729 ÷ 542"),
    "supply_chain_suppliers_total": (213, "年內有交易的活躍供應商"),
    "supply_chain_suppliers_hong_kong": (26, ""),
    "supply_chain_suppliers_mainland": (171, ""),
    "supply_chain_suppliers_other": (16, "日本、台灣、德國、馬來西亞"),
    "supply_chain_suppliers_assessed": (213, "全部簽署《供應商行為準則》並完成 ESG 自評；現場審核 42 家"),
    "product_recall_rate": (0, "無因安全與健康理由的回收"),
    "product_complaints": (9, "品質 6、交付 2、包裝 1"),
    "product_complaints_resolved_rate": (100, "全部於期內關閉，平均 6.4 天"),
    "privacy_data_breaches": (0, ""),
    "anti_corruption_legal_cases": (0, ""),
    "anti_corruption_training_directors": (7, "全體董事，各 2 小時"),
    "anti_corruption_training_employees": (486, "入職 74、高風險崗位 126、全員線上 286"),
    "anti_corruption_training_hours": (1120, "董事 14 + 僱員 1,106"),
    "community_donations": (186, "教育 96、環境 40、社區服務 50"),
    "community_volunteer_hours": (640, "6 次活動"),
    "community_volunteer_participants": (112, "143 人次去重"),
}

COMPANY_PROFILE_ZH_HANT = (
    "晉澧精密工業控股有限公司於 2006 年在香港成立，2016 年於香港聯合交易所主板上市，是一家專注於精密金屬沖壓件、"
    "連接器及組裝模組研發、製造及銷售的製造企業。公司總部位於香港觀塘，生產基地位於廣東省東莞市松山湖園區，"
    "由全資附屬公司東莞晉澧精密電子有限公司持有及營運。截至 2025 年 12 月 31 日，集團僱員 612 人。\n\n"
    "公司產品分為精密金屬沖壓件、連接器及組裝模組三類，應用於消費電子、工業設備及新能源汽車零部件領域；"
    "2025 年度營業收入 486.2 百萬港元，其中消費電子約佔 46%，新能源汽車零部件約佔 33%，工業設備及其他約佔 21%。"
    "公司具備精密級進模開發、高速沖壓與在線檢測及熱處理配套能力，東莞廠區沖壓車間自動化率約 68%，"
    "屋頂光伏 1.2 MWp 於 2023 年 6 月投運。\n\n"
    "公司持有 ISO 9001、ISO 14001、ISO 45001 及 IATF 16949 認證，研發及工程人員約 86 人，2025 年研發開支約 21.4 百萬港元。"
    "公司以「精密製造、穩健經營、以人為本」為經營理念，推進節能減排、廢棄物資源化與供應鏈協同，"
    "重視僱員發展、產品責任及社區參與。"
)

BOARD_OVERSIGHT_ZH_HANT = (
    "董事會對集團的環境、社會及管治事宜負最終責任，包括釐定管理方針及策略、審批重要性評估結果、審批目標並檢討進度、"
    "審批年度報告。2025 年董事會兩次專項審議相關事宜（3 月審議 2024 年度報告及重要性評估結果，9 月檢討目標進度及"
    "氣候情景分析）。日常管理授權予由執行董事兼財務總監牽頭的環境、社會及管治工作小組，小組每季開會，每半年向董事會"
    "提交書面匯報，重大事項須於 2 個工作日內向主席及行政總裁報告。"
)
BOARD_APPROACH_ZH_HANT = (
    "董事會確立以「合規營運、綠色製造、以人為本」為主軸的管理方針。重要議題每年透過三步識別及排序：以守則各層面及"
    "氣候相關披露為基礎形成 16 項議題清單；2025 年 10 月向僱員、客戶、供應商及投資者發出持份者問卷（回收 312 份）"
    "評估對持份者的重要性；11 月由工作小組及部門主管就對業務的重要性（收入、成本、合規及聲譽，綜合短、中、長期）評分，"
    "兩軸均以 4.0 分為閾值。結果 8 項議題屬高度重要，經董事會於 12 月審閱。氣候相關風險納入集團年度風險登記冊，"
    "由審核委員會檢討。"
)
BOARD_PROGRESS_ZH_HANT = (
    "董事會於 2024 年批准三項可量化目標並每年 9 月檢討進度：2030 年範圍 1 及範圍 2 溫室氣體排放密度較 2023 年下降 30%"
    "（2025 年為 16.6 tCO₂e／百萬港元，已下降 22.4%）；2027 年能源消耗密度較 2023 年下降 15%（2025 年 38.9 MWh／百萬港元，"
    "已下降 13.2%）；每年工傷個案數目不高於上一年度（2025 年 7 宗，2024 年 9 宗）。排放及能源密度直接影響電力成本與客戶"
    "碳足跡要求，工傷率影響生產連續性及僱員保留；董事會可按業務發展調整目標。"
)
GOVERNANCE_STRUCTURE_ZH_HANT = (
    "集團環境、社會及管治事宜由董事會、環境、社會及管治工作小組及各部門聯絡人三層參與管理。董事會負最終責任並每半年"
    "聽取書面匯報。工作小組 2021 年成立，職權範圍載於 JL-GOV-001，由執行董事兼財務總監黃頌恩牽頭，成員包括東莞廠總經理"
    "周啟明、環境健康安全主管羅子軒、生產部主管吳志強、品質部主管張永樂、採購部主管馮嘉欣、人力資源部主管李慧珊、"
    "資訊科技部主管郭俊傑及銷售及客戶服務部主管高美玲，公司秘書譚詠詩任小組秘書；小組每季開會，2025 年共 4 次。"
    "各部門指派聯絡人，按季度提交數據及進度。"
)
GOVERNANCE_DUTIES_ZH_HANT = (
    "董事會負責審批管理方針、目標及年度報告，檢討目標進度。工作小組負責統籌重要性評估、目標分解與跟蹤、氣候相關風險"
    "評估、數據匯總複核及報告編製，並審核相關政策的制訂與修訂。環境健康安全部負責排放、廢棄物、能源、用水及職業安全"
    "數據；人力資源部負責僱傭、培訓、勞工準則及社區投資；採購部負責供應鏈管理及供應商評核；品質部及銷售及客戶服務部"
    "負責產品責任與客戶投訴；資訊科技部負責資料保障；公司秘書處負責反貪污、合規及董事會匯報。數據經部門主管簽核，"
    "環境及安全數據由環境健康安全主管複核，其餘由公司秘書複核。"
)

FIELD_ANSWERS_ZH_HANT: dict[str, object] = {
    "field.company_short_name": "晉澧精密",
    "field.industry_major_category": "製造業",
    "field.industry_division": "精密金屬沖壓件及連接器製造",
    "field.report_publication_channel": "聯交所披露易及公司網站刊發",
    "field.report_publication_website_url": "https://www.jinli-precision.example.hk",
    "field.report_approval_year": 2026,
    "field.report_approval_month": "2026-03",
    "company_profile": COMPANY_PROFILE_ZH_HANT,
    "company_certifications": "ISO 9001 品質管理體系、ISO 14001 環境管理體系、ISO 45001 職業健康安全管理體系、IATF 16949 汽車業品質管理體系",
    "board_statement.q_oversight": BOARD_OVERSIGHT_ZH_HANT,
    "board_statement.q_management_approach": BOARD_APPROACH_ZH_HANT,
    "board_statement.q_progress_review": BOARD_PROGRESS_ZH_HANT,
    "sustainability_governance_structure": GOVERNANCE_STRUCTURE_ZH_HANT,
    "sustainability_governance_duties": GOVERNANCE_DUTIES_ZH_HANT,
    "appendix.reader_feedback.address": "香港九龍觀塘鴻圖道 1 號晉澧中心 12 樓",
    "appendix.reader_feedback.email": "esg@jinli-precision.example.hk",
    "appendix.reader_feedback.phone": "+852 0000 0000",
}

# Structured Aspect judgements (select questions only); free-text questions stay empty so the uploaded
# materials carry the substance. Options are quoted verbatim from topic_intake/*.yaml.
ASPECT_JUDGEMENTS_ZH_HANT: tuple[tuple[str, object, str | None], ...] = (
    ("climate.q_climate_risks", ["極端天氣（颱風、暴雨、水浸）", "持續高溫", "碳定價及排放監管政策變化", "客戶及市場的低碳要求", "能源價格波動"],
     "東莞廠及香港辦公室位於華南沿岸；2025 年因颱風預警停產 2 天；消費電子及汽車客戶要求提供碳足跡及減排承諾。"),
    ("climate.q_climate_opportunities", ["能源及資源效率提升", "低碳產品或服務", "可再生能源使用"],
     "節能改造累計年節電約 1,350 MWh；新能源汽車零部件收入佔比升至 33%；評估倉庫屋頂光伏擴建。"),
    ("climate.q_scenario_analysis", "已開展情景分析",
     "2025 年首次定性情景分析，參考 2°C 有序轉型及 4°C 高排放兩個情景；未量化財務影響，計劃 2026 年作定量敏感度測算。"),
    ("emissions.q_emission_sources", ["燃燒設備（鍋爐、發電機）", "公司車輛", "生產工序（噴塗、焊接、清洗等）", "生產廢水排放", "生活污水排放"],
     "天然氣退火及熱處理爐、備用發電機、清洗及脫脂工序溶劑揮發；廢水經預處理後排入園區污水管網。電鍍全部外協。"),
    ("energy.q_renewable_energy", "自建太陽能光伏等可再生能源設施",
     "東莞廠屋頂光伏 1.2 MWp，2023 年 6 月投運，2025 年自發自用 1,360 MWh。"),
    ("waste.q_hazardous_waste", "有，並交由持牌承辦商處置",
     "廢切削液及廢油、含油抹布及手套、廢活性炭、廢化學品包裝等，全部執行電子轉移聯單。"),
    ("water.q_water_sourcing_issue", "沒有遇到問題", "東莞廠及香港辦公室均使用市政供水。"),
    ("natural_resources.q_significant_impacts", ["噪音", "原材料開採或採購"],
     "高速沖床為主要噪音源，廠界噪音年檢符合標準；主要原材料為銅合金及不銹鋼帶材。"),
    ("health_safety.q_ohs_incidents", "有工傷事故，無因工亡故", "2025 年工傷個案 7 宗，損失工作日 126 天；連續三年無因工亡故。"),
    ("labour_standards.q_labour_violations", "沒有發現", "2025 年 5 月及 11 月各抽查 60 份入職檔案，未發現童工或強制勞工。"),
    ("anti_corruption.q_corruption_cases", "沒有", "2025 年無涉及集團或其僱員的貪污訴訟案件；收到舉報 2 宗，1 宗屬實並已處理。"),
    ("community_investment.q_focus_areas", ["教育", "環境", "扶貧及弱勢社群"],
     "聚焦香港觀塘及東莞松山湖社區：職業技術學校獎學金、植樹及海岸清潔、長者探訪。"),
)

# Fixed pillar questions per Aspect: (roles supplement, certification option, certification supplement).
ROLE_OPTION = "設有專責部門或崗位負責"
POLICY_OPTION = "設有相關政策、程序或管理要求"
FIXED_PILLAR_ANSWERS_ZH_HANT: dict[str, tuple[str, str, str | None, str]] = {
    "climate": ("環境健康安全部與財務部聯合負責氣候相關風險評估及排放數據，ESG 工作小組召集人統籌。", "持有相關認證", "ISO 14001 環境管理體系。", "《氣候相關風險管理指引》（JL-EHS-005）。"),
    "emissions": ("環境健康安全部負責廢氣、廢水監測及排污許可管理。", "持有相關認證", "ISO 14001 環境管理體系。", "《環境管理制度》（JL-EHS-001），東莞廠持有排污許可證。"),
    "waste": ("環境健康安全部負責廢棄物分類、貯存、轉移及台賬。", "持有相關認證", "ISO 14001 環境管理體系。", "《廢棄物管理程序》（JL-EHS-003）。"),
    "energy": ("生產部負責設備能效及節能改造，環境健康安全部負責計量統計。", "持有相關認證", "ISO 14001 環境管理體系。", "《能源管理辦法》（JL-EHS-002）。"),
    "water": ("環境健康安全部負責用水計量及廢水預處理，行政部負責生活區節水。", "持有相關認證", "ISO 14001 環境管理體系。", "《環境管理制度》（JL-EHS-001）第三章。"),
    "materials": ("生產部物流組負責包裝材料選用及統計，採購部核對再生材料聲明。", "暫無相關認證", None, "《包裝材料管理指引》（JL-EHS-006）。"),
    "natural_resources": ("環境健康安全部負責噪音監測及環境因素識別。", "持有相關認證", "ISO 14001 環境管理體系。", "《環境管理制度》（JL-EHS-001）。"),
    "employment": ("人力資源部負責招聘、薪酬、福利及僱員關係。", "暫無相關認證", None, "《僱員手冊》（JL-HR-001），遵守香港《僱傭條例》及內地《勞動合同法》。"),
    "health_safety": ("環境健康安全部負責職業健康與安全管理，東莞廠安全生產委員會每季檢討。", "持有相關認證", "ISO 45001 職業健康安全管理體系。", "《職業健康與安全管理制度》（JL-EHS-004）。"),
    "training": ("人力資源部負責培訓需求調查、年度培訓計劃及記錄。", "暫無相關認證", None, "《僱員手冊》（JL-HR-001）第六章培訓與發展。"),
    "labour_standards": ("人力資源部負責入職核查及檔案抽查，採購部把同等要求延伸至供應商。", "暫無相關認證", None, "《僱員手冊》（JL-HR-001）第二、三章，《供應商行為準則》。"),
    "supply_chain": ("採購部負責供應商准入、評核、審核及退出，品質部與環境健康安全部參與現場審核。", "暫無相關認證", None, "《供應商管理辦法》（JL-PUR-001）及《供應商行為準則》。"),
    "product": ("品質部負責品質保證、產品安全及回收程序，銷售及客戶服務部負責投訴處理。", "持有相關認證", "ISO 9001 品質管理體系、IATF 16949 汽車業品質管理體系。", "《品質管理手冊》（JL-QA-001）、《客戶服務及投訴處理程序》（JL-CS-001）。"),
    "privacy": ("資訊科技部負責資料安全措施，公司秘書負責法規合規審核。", "暫無相關認證", None, "《資料保障及私隱政策》（JL-IT-001）。"),
    "anti_corruption": ("公司秘書處負責政策執行及舉報調查，審核委員會監督。", "暫無相關認證", None, "《反貪污及舉報政策》（JL-LEG-001），遵守香港《防止賄賂條例》。"),
    "community_investment": ("人力資源部企業社會責任小組統籌社區投資及義工活動。", "暫無相關認證", None, "社區投資聚焦教育、環境及社區服務三個範疇，義工假每年 1 天。"),
}

GHG_STANDARD_ZH_HANT = "《溫室氣體核算體系》（GHG Protocol）"

COMPANY_PROFILE_EN = (
    "Jinli Precision Industrial Holdings Limited was founded in Hong Kong in 2006 and listed on the Main Board of The Stock "
    "Exchange of Hong Kong Limited in 2016. It develops, manufactures and sells precision metal stamping parts, connectors and "
    "assembled modules. The head office is in Kwun Tong, Hong Kong, and the production base in Songshan Lake, Dongguan, "
    "Guangdong, is held and operated by the wholly owned subsidiary Dongguan Jinli Precision Electronics Co., Ltd. The group "
    "employed 612 people as at 31 December 2025.\n\n"
    "Products fall into three lines — precision metal stamping parts, connectors and assembled modules — serving consumer "
    "electronics, industrial equipment and new energy vehicle component customers. Revenue for 2025 was HK$486.2 million, of "
    "which consumer electronics accounted for about 46%, new energy vehicle components about 33% and industrial equipment and "
    "others about 21%. The company runs precision progressive die development, high-speed stamping with in-line inspection and "
    "in-house heat treatment; the Dongguan stamping shop is about 68% automated and a 1.2 MWp rooftop solar system has operated "
    "since June 2023.\n\n"
    "The company holds ISO 9001, ISO 14001, ISO 45001 and IATF 16949 certifications, employs about 86 research and engineering "
    "staff and spent about HK$21.4 million on research and development in 2025. Guided by precision manufacturing, prudent "
    "operation and a people-first culture, it advances energy saving, waste recovery and supply chain collaboration and values "
    "employee development, product responsibility and community participation."
)
BOARD_OVERSIGHT_EN = (
    "The Board holds ultimate responsibility for environmental, social and governance matters, including setting the management "
    "approach and strategy, approving the materiality assessment results, approving targets and reviewing progress, and approving "
    "the annual report. In 2025 the Board considered these matters at two dedicated sessions (March: the 2024 report and "
    "materiality results; September: target progress and the climate scenario analysis). Day-to-day management is delegated to "
    "the ESG working group led by the executive director and chief financial officer, which meets quarterly, reports to the Board "
    "in writing every half year and must report material matters to the Chairman and the Chief Executive within two working days."
)
BOARD_APPROACH_EN = (
    "The Board has set a management approach built on compliant operation, green manufacturing and a people-first culture. "
    "Material issues are identified and ranked each year in three steps: a list of 16 topics built from the Aspects of the Code "
    "and the climate-related disclosures; a stakeholder questionnaire in October 2025 (312 responses from employees, customers, "
    "suppliers and investors) assessing importance to stakeholders; and a management workshop in November in which the working "
    "group and department heads scored importance to the business (revenue, cost, compliance and reputation over the short, "
    "medium and long term), with a threshold of 4.0 on both axes. Eight topics were highly material and the Board reviewed the "
    "results in December. Climate-related risks are entered in the group risk register reviewed by the Audit Committee."
)
BOARD_PROGRESS_EN = (
    "In 2024 the Board approved three quantified targets and reviews progress every September: a 30% reduction in Scope 1 and "
    "Scope 2 greenhouse gas emission intensity by 2030 against 2023 (16.6 tCO2e per HK$ million in 2025, down 22.4%); a 15% "
    "reduction in energy consumption intensity by 2027 against 2023 (38.9 MWh per HK$ million in 2025, down 13.2%); and no more "
    "work injury cases than the previous year (7 in 2025 against 9 in 2024). Emission and energy intensity bear directly on "
    "electricity costs and customers' carbon footprint requirements, and the injury rate on production continuity and "
    "employee retention; the Board may adjust the targets as the business develops."
)
GOVERNANCE_STRUCTURE_EN = (
    "Environmental, social and governance matters are managed at three levels: the Board, the ESG working group and departmental "
    "coordinators. The Board holds ultimate responsibility and receives a written report every half year. The working group, "
    "formed in 2021 with terms of reference JL-GOV-001, is led by the executive director and chief financial officer Wong Chung-yan "
    "and comprises the Dongguan plant general manager Chow Kai-ming, the EHS manager Law Tsz-hin, the production manager Ng "
    "Chi-keung, the quality manager Cheung Wing-lok, the procurement manager Fung Ka-yan, the human resources manager Li Wai-shan, "
    "the IT manager Kwok Chun-kit and the sales and customer service manager Ko Mei-ling, with the company secretary Tam Wing-sze "
    "as secretary; it meets quarterly and met four times in 2025. Each department appoints a coordinator who submits data and "
    "progress quarterly."
)
GOVERNANCE_DUTIES_EN = (
    "The Board approves the management approach, targets and annual report and reviews target progress. The working group "
    "coordinates the materiality assessment, target allocation and tracking, climate risk assessment, data consolidation and "
    "review, and report preparation, and reviews the making and revision of related policies. The EHS department owns emissions, "
    "waste, energy, water and occupational safety data; human resources owns employment, training, labour standards and community "
    "investment; procurement owns supply chain management and supplier evaluation; quality and sales and customer service own "
    "product responsibility and complaints; IT owns data protection; and the company secretary's office owns anti-corruption, "
    "compliance and Board reporting. Data are signed off by department heads, environmental and safety data are reviewed by the "
    "EHS manager and the rest by the company secretary."
)
FIELD_ANSWERS_EN: dict[str, object] = {
    "field.company_short_name": "Jinli Precision",
    "field.industry_major_category": "Manufacturing",
    "field.industry_division": "Precision metal stamping parts and connectors",
    "field.report_publication_channel": "HKEXnews and the company website",
    "field.report_publication_website_url": "https://www.jinli-precision.example.hk",
    "field.report_approval_year": 2026,
    "field.report_approval_month": "2026-03",
    "company_profile": COMPANY_PROFILE_EN,
    "company_certifications": "ISO 9001 quality management, ISO 14001 environmental management, ISO 45001 occupational health and safety management, IATF 16949 automotive quality management",
    "board_statement.q_oversight": BOARD_OVERSIGHT_EN,
    "board_statement.q_management_approach": BOARD_APPROACH_EN,
    "board_statement.q_progress_review": BOARD_PROGRESS_EN,
    "sustainability_governance_structure": GOVERNANCE_STRUCTURE_EN,
    "sustainability_governance_duties": GOVERNANCE_DUTIES_EN,
    "appendix.reader_feedback.address": "12/F, Jinli Centre, 1 Hung To Road, Kwun Tong, Kowloon, Hong Kong",
    "appendix.reader_feedback.email": "esg@jinli-precision.example.hk",
    "appendix.reader_feedback.phone": "+852 0000 0000",
}
ASPECT_JUDGEMENTS_EN: tuple[tuple[str, object, str | None], ...] = (
    ("climate.q_climate_risks", ["Extreme weather (typhoons, rainstorms, flooding)", "Prolonged heat", "Carbon pricing and emissions regulation", "Low-carbon requirements from customers and markets", "Energy price volatility"],
     "The Dongguan plant and Hong Kong office lie on the South China coast; a typhoon warning halted production for two days in 2025; consumer electronics and automotive customers ask for carbon footprints and reduction commitments."),
    ("climate.q_climate_opportunities", ["Energy and resource efficiency", "Low-carbon products or services", "Use of renewable energy"],
     "Energy retrofits save about 1,350 MWh a year; new energy vehicle components rose to 33% of revenue; a warehouse rooftop solar extension is under evaluation."),
    ("climate.q_scenario_analysis", "Scenario analysis carried out",
     "First qualitative scenario analysis in 2025 against a 2°C orderly transition and a 4°C high-emission scenario; financial effects not quantified, a quantitative sensitivity test is planned for 2026."),
    ("emissions.q_emission_sources", ["Combustion equipment (boilers, generators)", "Company vehicles", "Production processes (spraying, welding, cleaning, etc.)", "Industrial wastewater discharge", "Domestic sewage discharge"],
     "Natural gas annealing and heat treatment furnaces, standby generators, solvent evaporation from cleaning and degreasing; wastewater is pre-treated before discharge to the park sewer. All plating is outsourced."),
    ("energy.q_renewable_energy", "Own solar photovoltaic or other renewable installations",
     "A 1.2 MWp rooftop solar system at the Dongguan plant, operating since June 2023, supplied 1,360 MWh for own use in 2025."),
    ("waste.q_hazardous_waste", "Yes, disposed of through licensed contractors",
     "Waste cutting fluid and oil, oily rags and gloves, spent activated carbon and chemical packaging, all under electronic transfer manifests."),
    ("water.q_water_sourcing_issue", "No issue", "Both the Dongguan plant and the Hong Kong office use municipal water."),
    ("natural_resources.q_significant_impacts", ["Noise", "Raw material extraction or sourcing"],
     "High-speed presses are the main noise source and boundary noise passed the annual test; main raw materials are copper alloy and stainless steel strip."),
    ("health_safety.q_ohs_incidents", "Injuries occurred, no fatality", "Seven work injury cases and 126 lost days in 2025; no work-related fatality for three consecutive years."),
    ("labour_standards.q_labour_violations", "None discovered", "Sixty personnel files were sampled in May and again in November 2025; no child or forced labour was found."),
    ("anti_corruption.q_corruption_cases", "None", "No concluded corruption case against the group or its employees in 2025; two reports were received, one substantiated and dealt with."),
    ("community_investment.q_focus_areas", ["Education", "Environmental concerns", "Poverty relief and vulnerable groups"],
     "Focused on the Kwun Tong and Songshan Lake communities: vocational school scholarships, tree planting and coastal clean-ups, elderly visits."),
)
ROLE_OPTION_EN = "A dedicated department or position is responsible"
POLICY_OPTION_EN = "Policies, procedures or management requirements in place"
CERT_HELD_EN = "Certifications held"
CERT_NONE_EN = "No related certification"
FIXED_PILLAR_ANSWERS_EN: dict[str, tuple[str, str, str | None, str]] = {
    "climate": ("The EHS and finance departments jointly assess climate-related risks and own emissions data; the ESG working group convener coordinates.", CERT_HELD_EN, "ISO 14001 environmental management system.", "Climate-related Risk Management Guideline (JL-EHS-005)."),
    "emissions": ("The EHS department monitors air and water emissions and manages the pollutant discharge permit.", CERT_HELD_EN, "ISO 14001 environmental management system.", "Environmental Management Policy (JL-EHS-001); the Dongguan plant holds a pollutant discharge permit."),
    "waste": ("The EHS department manages waste sorting, storage, transfer and records.", CERT_HELD_EN, "ISO 14001 environmental management system.", "Waste Management Procedure (JL-EHS-003)."),
    "energy": ("The production department owns equipment efficiency and retrofits; the EHS department owns metering and statistics.", CERT_HELD_EN, "ISO 14001 environmental management system.", "Energy Management Procedure (JL-EHS-002)."),
    "water": ("The EHS department owns water metering and wastewater pre-treatment; administration owns water saving in living areas.", CERT_HELD_EN, "ISO 14001 environmental management system.", "Environmental Management Policy (JL-EHS-001), chapter 3."),
    "materials": ("The logistics team of the production department selects and records packaging; procurement checks recycled-content declarations.", CERT_NONE_EN, None, "Packaging Material Guideline (JL-EHS-006)."),
    "natural_resources": ("The EHS department monitors noise and identifies environmental aspects.", CERT_HELD_EN, "ISO 14001 environmental management system.", "Environmental Management Policy (JL-EHS-001)."),
    "employment": ("Human resources owns recruitment, pay, benefits and employee relations.", CERT_NONE_EN, None, "Employee Handbook (JL-HR-001); compliant with the Hong Kong Employment Ordinance and the Mainland Labour Contract Law."),
    "health_safety": ("The EHS department manages occupational health and safety; the Dongguan plant safety committee reviews quarterly.", CERT_HELD_EN, "ISO 45001 occupational health and safety management system.", "Occupational Health and Safety Management Policy (JL-EHS-004)."),
    "training": ("Human resources owns the training needs survey, annual training plan and records.", CERT_NONE_EN, None, "Employee Handbook (JL-HR-001), chapter 6 on training and development."),
    "labour_standards": ("Human resources verifies new hires and samples personnel files; procurement extends the same requirements to suppliers.", CERT_NONE_EN, None, "Employee Handbook (JL-HR-001), chapters 2 and 3; Supplier Code of Conduct."),
    "supply_chain": ("Procurement owns supplier admission, evaluation, audits and exit; quality and EHS join on-site audits.", CERT_NONE_EN, None, "Supplier Management Procedure (JL-PUR-001) and the Supplier Code of Conduct."),
    "product": ("Quality owns quality assurance, product safety and recall procedures; sales and customer service owns complaints.", CERT_HELD_EN, "ISO 9001 quality management system; IATF 16949 automotive quality management system.", "Quality Manual (JL-QA-001); Customer Service and Complaint Handling Procedure (JL-CS-001)."),
    "privacy": ("IT owns data security measures; the company secretary reviews legal compliance.", CERT_NONE_EN, None, "Data Protection and Privacy Policy (JL-IT-001)."),
    "anti_corruption": ("The company secretary's office implements the policy and investigates reports; the Audit Committee oversees.", CERT_NONE_EN, None, "Anti-corruption and Whistle-blowing Policy (JL-LEG-001); compliant with the Hong Kong Prevention of Bribery Ordinance."),
    "community_investment": ("The corporate social responsibility team of human resources coordinates community investment and volunteering.", CERT_NONE_EN, None, "Community investment focuses on education, the environment and community service; one day of volunteer leave a year."),
}
GHG_STANDARD_EN = "GHG Protocol Corporate Accounting and Reporting Standard"

LANGUAGES: dict[str, dict[str, object]] = {
    "zh-Hant": {
        "profile": "hkex_zh_hant@1",
        "fixture_id": "jinli-synthetic-full-hkex-zh-hant-v1",
        "entity": "晉澧精密工業控股有限公司",
        "consolidation_scope": "本公司及全部附屬公司",
        "fields": FIELD_ANSWERS_ZH_HANT,
        "judgements": ASPECT_JUDGEMENTS_ZH_HANT,
        "fixed_pillar": FIXED_PILLAR_ANSWERS_ZH_HANT,
        "role_option": ROLE_OPTION,
        "policy_option": POLICY_OPTION,
        "ghg_standard": GHG_STANDARD_ZH_HANT,
    },
    "en": {
        "profile": "hkex_en@1",
        "fixture_id": "jinli-synthetic-full-hkex-en-v1",
        "entity": "Jinli Precision Industrial Holdings Limited",
        "consolidation_scope": "The Company and all its subsidiaries",
        "fields": FIELD_ANSWERS_EN,
        "judgements": ASPECT_JUDGEMENTS_EN,
        "fixed_pillar": FIXED_PILLAR_ANSWERS_EN,
        "role_option": ROLE_OPTION_EN,
        "policy_option": POLICY_OPTION_EN,
        "ghg_standard": GHG_STANDARD_EN,
    },
}


def build_input_writes(adapter: LightweightReportInputAdapter, spec: dict[str, object]) -> list[dict[str, object]]:
    """Encode answers and KPI values as fingerprinted inputWrites."""

    writes: list[dict[str, object]] = []

    def append(target_key: str, answer: object, supplement: str | None = None) -> None:
        entry: dict[str, object] = {
            "target_key": target_key,
            "answer": answer,
            "expected_definition_fingerprint": adapter.target_fingerprint(target_key),
            # Optimistic lock: the target must still be empty when the write is applied.
            "expected_target_fingerprint": adapter.fingerprint(None, None),
        }
        if supplement:
            entry["supplement"] = supplement
        writes.append(entry)

    for key, answer in spec["fields"].items():  # type: ignore[attr-defined]
        append(key, answer)
    for key, answer, supplement in spec["judgements"]:  # type: ignore[misc]
        append(key, answer, supplement)
    for prefix, (roles, certification, certification_note, policy) in spec["fixed_pillar"].items():  # type: ignore[attr-defined]
        append(f"{prefix}.q_governance_roles", spec["role_option"], roles)
        append(f"{prefix}.q_governance_policies", spec["policy_option"], policy)
        append(f"{prefix}.q_governance_certifications", certification, certification_note)
    for metric_key, (value, note) in METRICS.items():
        append(f"metric.{metric_key}", value, note or None)
    return writes


def build_recipe(language: str) -> dict[str, object]:
    spec = LANGUAGES[language]
    package = knowledge_package_for_profile(str(spec["profile"]))
    adapter = LightweightReportInputAdapter(package)
    return {
        "contract": "sustainability_desk.local_e2e_report_input_fixture.v1",
        "fixtureId": spec["fixture_id"],
        "artifactPurpose": "local_e2e_test",
        "fixtureBasis": "simulated_for_local_e2e",
        "reportProfileId": spec["profile"],
        "corpusId": MANIFEST_ID,
        "reportingEntity": spec["entity"],
        "reportingYear": REPORTING_YEAR,
        "consolidationScope": spec["consolidation_scope"],
        "assessmentScores": {
            topic: {"financialScore": financial, "impactScore": impact} for topic, (financial, impact) in SCORES.items()
        },
        "greenhouseGasAccountingStandard": spec["ghg_standard"],
        "inputWrites": build_input_writes(adapter, spec),
    }


def build_manifest() -> dict[str, object]:
    docx_files = sorted(DOCX_DIR.glob("*.docx"))
    if not docx_files:
        raise SystemExit(f"{DOCX_DIR} has no docx; run build_materials.py first")
    files: list[dict[str, object]] = []
    for ordinal, path in enumerate(docx_files, start=1):
        data = path.read_bytes()
        files.append(
            {
                "caseId": f"material-{ordinal:02d}",
                "ordinal": ordinal,
                "relativePath": path.name,
                "selectionRationale": "晉澧合成 corpus 的語義資料，按文件名表達內容歸屬。",
                "expectedKind": "docx",
                "expectedMediaType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "expectedSizeBytes": len(data),
                "expectedSha256": hashlib.sha256(data).hexdigest(),
                "expectedPdfPageCount": None,
                "declaration": {
                    "description": f"{path.stem}，晉澧精密 2025 年度環境、社會及管治相關資料。",
                    "role": "semantic_material",
                    "topic_tags": ["uncertain"],
                },
            }
        )
    batch_size = 10
    batches = [[entry["caseId"] for entry in files[index : index + batch_size]] for index in range(0, len(files), batch_size)]
    return {
        "contract": "sustainability_desk.local_e2e_selection_manifest.v3",
        "manifestId": MANIFEST_ID,
        "artifactPurpose": "local_e2e_test",
        "corpusRootRelative": str(DOCX_DIR.relative_to(REPO_ROOT)),
        "selectionBasis": "path_and_filename_only",
        "selectionPolicyVersion": "jinli-synthetic-corpus.v1",
        "selectedFileCount": len(files),
        "excludedPathSegments": [],
        "uploadBatches": batches,
        "files": files,
    }


def main() -> None:
    outputs: list[tuple[Path, dict[str, object]]] = [
        (FIXTURE_DIR / f"jinli_report_inputs.{language}.yaml", build_recipe(language)) for language in LANGUAGES
    ]
    outputs.append((FIXTURE_DIR / "jinli_materials.yaml", build_manifest()))
    for path, payload in outputs:
        path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        summary = (
            f"{len(payload['inputWrites'])} writes / {len(payload['assessmentScores'])} scores"  # type: ignore[arg-type]
            if "inputWrites" in payload
            else f"{payload['selectedFileCount']} files"
        )
        print(f"wrote {path.name} ({summary})")


if __name__ == "__main__":
    main()
