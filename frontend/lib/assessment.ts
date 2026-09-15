// ABOUTME: 重要性评分前端只拥有用户输入默认值；分类、固定议题与计数统一由后端 resolver 负责。
// ABOUTME: 本模块不得实现象限判定，避免浏览器与 Registry/后端解析器形成双重真相源。
import type { MaterialityScoreInput, MaterialityThreshold } from "./schema";

export type ScoredTopic = MaterialityScoreInput;

export const DEFAULT_THRESHOLD: MaterialityThreshold = { financial: 4.0, impact: 4.0 };
