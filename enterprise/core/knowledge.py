"""面向企业管理分析的本地知识资料库与混合语义检索。"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any

from enterprise.adapters.documents import parse_document

from .catalog import WORKFLOW_DEPARTMENTS
from .storage import EnterpriseStore, sanitize_filename

DEPARTMENTS = ["公司级", "审计与合同", "人力管理", "行政管理", "财务管理"]
DOCUMENT_TYPES = ["公司章程", "部门制度", "业务规范", "历史案例", "会议决议", "其他"]
AUTHORITY_LEVELS = {
    "公司章程": (1, "一级｜公司治理依据"),
    "部门制度": (2, "二级｜已生效部门制度"),
    "业务规范": (3, "三级｜业务规范/会议决议"),
    "会议决议": (3, "三级｜业务规范/会议决议"),
    "历史案例": (4, "四级｜已确认历史事实"),
    "其他": (5, "五级｜参考资料"),
}

_SYNONYM_GROUPS = [
    ("差旅", "出差"),
    ("报账", "报销", "费用申请"),
    ("规章", "制度", "办法", "规定"),
    ("公司章程", "治理规则", "议事规则"),
    ("员工", "职工", "劳动者"),
    ("招聘", "招录", "录用"),
    ("供应商", "合作方", "乙方"),
    ("预算", "费用计划", "资金计划"),
    ("历史问题", "历史案例", "过往事项", "以前问题"),
    ("审计", "检查", "复核", "监督"),
]


class KnowledgeBase:
    """管理制度、章程、业务规范和历史案件记忆。"""

    def __init__(self, store: EnterpriseStore) -> None:
        self.store = store

    def add_text(
        self,
        title: str,
        content: str,
        department: str,
        document_type: str,
        actor: str = "本地用户",
        *,
        version: str = "",
        effective_date: str = "",
        source_ref: str = "",
        status: str = "有效",
        metadata: dict[str, Any] | None = None,
        confirmed_history: bool = False,
    ) -> str:
        """保存一份知识资料并生成可检索分块。"""

        title = title.strip()
        content = content.strip()
        if not title or not content:
            raise ValueError("知识资料标题和正文不能为空")
        if department not in DEPARTMENTS:
            raise ValueError(f"未知业务板块: {department}")
        if document_type not in DOCUMENT_TYPES:
            raise ValueError(f"未知资料类型: {document_type}")
        if document_type == "历史案例" and not confirmed_history:
            raise ValueError("历史案例只能由已确认或已关闭的工作台案件生成")
        if not source_ref:
            digest = hashlib.sha256(
                f"{department}|{document_type}|{title}|{content}".encode("utf-8")
            ).hexdigest()
            source_ref = f"inline:{digest[:20]}"
        return self.store.save_knowledge_document(
            title,
            department,
            document_type,
            content,
            _chunk_text(content),
            actor=actor,
            version=version,
            effective_date=effective_date,
            source_ref=source_ref,
            status=status,
            metadata=metadata,
        )

    def add_upload(
        self,
        name: str,
        content: bytes,
        department: str,
        document_type: str,
        actor: str = "本地用户",
        **metadata: Any,
    ) -> str:
        """归档并解析浏览器上传的知识资料。"""

        digest = hashlib.sha256(content).hexdigest()
        source_dir = self.store.root / "knowledge_sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        safe_name = sanitize_filename(name)
        path = source_dir / f"{digest[:12]}_{safe_name}"
        path.write_bytes(content)
        document = parse_document(path)
        return self.add_text(
            title=metadata.pop("title", "") or safe_name,
            content=document.text,
            department=department,
            document_type=document_type,
            actor=actor,
            source_ref=metadata.pop("source_ref", "") or f"file:{digest}",
            metadata={"file_name": safe_name, "sha256": digest, "stored_path": str(path)},
            **metadata,
        )

    def search(
        self,
        query: str,
        *,
        departments: list[str] | None = None,
        document_types: list[str] | None = None,
        limit: int = 6,
        exclude_source_ref: str = "",
    ) -> list[dict[str, Any]]:
        """使用同义词扩展、TF-IDF 与字符 n-gram 完成本地混合检索。"""

        query_tokens = _semantic_tokens(query)
        if not query_tokens:
            return []
        chunks = self.store.list_knowledge_chunks(departments, document_types)
        if exclude_source_ref:
            chunks = [item for item in chunks if item["source_ref"] != exclude_source_ref]
        if not chunks:
            return []
        tokenized = [_semantic_tokens(item["excerpt"]) for item in chunks]
        document_frequency: Counter[str] = Counter()
        for tokens in tokenized:
            document_frequency.update(set(tokens))
        total = len(chunks)
        query_counts = Counter(query_tokens)
        scored: list[dict[str, Any]] = []
        for item, tokens in zip(chunks, tokenized, strict=True):
            chunk_counts = Counter(tokens)
            shared = set(query_counts) & set(chunk_counts)
            if not shared:
                continue
            numerator = 0.0
            query_norm = 0.0
            chunk_norm = 0.0
            vocabulary = set(query_counts) | set(chunk_counts)
            for token in vocabulary:
                idf = math.log((total + 1) / (document_frequency.get(token, 0) + 1)) + 1
                query_weight = (1 + math.log(query_counts[token])) * idf if query_counts[token] else 0
                chunk_weight = (1 + math.log(chunk_counts[token])) * idf if chunk_counts[token] else 0
                numerator += query_weight * chunk_weight
                query_norm += query_weight**2
                chunk_norm += chunk_weight**2
            score = numerator / math.sqrt(query_norm * chunk_norm) if query_norm and chunk_norm else 0
            matched_terms = sorted(shared, key=lambda value: (-len(value), value))[:8]
            candidate = dict(item)
            candidate["score"] = round(min(score, 1.0), 4)
            if item["metadata"].get("sample"):
                authority_rank, authority_label = 99, "规划样本｜不具正式效力"
            else:
                authority_rank, authority_label = AUTHORITY_LEVELS[item["document_type"]]
            candidate["authority_rank"] = authority_rank
            candidate["authority_label"] = authority_label
            candidate["matched_terms"] = matched_terms
            candidate["locator"] = f"第 {item['position'] + 1} 个知识分块"
            candidate["comparison"] = _comparison_text(candidate)
            scored.append(candidate)
        scored.sort(key=lambda item: item["score"], reverse=True)
        output: list[dict[str, Any]] = []
        seen_documents: set[str] = set()
        for item in scored:
            if item["document_id"] in seen_documents or item["score"] < 0.015:
                continue
            seen_documents.add(item["document_id"])
            output.append(item)
            if len(output) >= limit:
                break
        output.sort(key=lambda item: (item["authority_rank"], -item["score"]))
        return output

    def list_documents(
        self, department: str | None = None, document_type: str | None = None
    ) -> list[dict[str, Any]]:
        """列出知识资料。"""

        return self.store.list_knowledge_documents(department, document_type, status=None)

    def remember_case(
        self,
        case_id: str,
        workflow_id: str,
        title: str,
        summary: str,
        findings: list[dict[str, Any]],
        actor: str,
    ) -> str:
        """把已完成案件压缩为可供后续分析召回的历史记忆。"""

        department = WORKFLOW_DEPARTMENTS[workflow_id]
        finding_lines = [
            f"[{item.get('severity', '')}/{item.get('review_status', '案件已确认')}] "
            f"{item.get('title', '')}：{item.get('description', '')} "
            f"复核意见：{item.get('review_comment') or '随案件确认'}"
            for item in findings[:12]
        ]
        content = "\n".join(
            [
                f"历史案件：{title}",
                f"业务板块：{department}",
                f"分析时摘要（仅作背景，不代表确认结论）：{summary}",
            ]
            + (
                ["经人工确认的问题："] + finding_lines
                if finding_lines
                else ["经人工确认的问题：无"]
            )
        )
        return self.add_text(
            title=f"历史案件记忆｜{title}",
            content=content,
            department=department,
            document_type="历史案例",
            actor=actor,
            source_ref=case_id,
            metadata={"case_id": case_id, "workflow_id": workflow_id},
            confirmed_history=True,
        )

    def seed_hotel_baseline(self, actor: str = "本地用户") -> dict[str, int]:
        """写入保利酒店场景的规划样本，不冒充企业现行正式制度。"""

        created = 0
        for index, item in enumerate(_HOTEL_BASELINE, start=1):
            self.add_text(
                title=item["title"],
                content=item["content"],
                department=item["department"],
                document_type=item["document_type"],
                actor=actor,
                version="规划版 V1.0",
                source_ref=f"hotel-baseline:{index}",
                status="规划样本",
                metadata={"sample": True, "disclaimer": "规划样本，需替换为企业有效文件"},
            )
            created += 1
        return {"created": created}


def build_analysis_query(result: Any, documents: list[Any]) -> str:
    """从业务结果和原始材料构造知识召回查询。"""

    fields = " ".join(f"{key} {value}" for key, value in result.fields.items())
    findings = " ".join(
        f"{item.category} {item.title} {item.description}" for item in result.findings
    )
    source = " ".join(document.text[:3500] for document in documents)
    return f"{result.title} {result.summary} {fields} {findings} {source}"


def compare_analysis_matches(
    result: Any, matches: list[dict[str, Any]], documents: list[Any]
) -> list[dict[str, Any]]:
    """把召回条款与本次具体发现项关联，形成负责人可执行的核对意见。"""

    for match in matches:
        excerpt_tokens = {token for token in _semantic_tokens(match["excerpt"]) if len(token) >= 2}
        related: list[tuple[int, Any, list[str]]] = []
        for finding in result.findings:
            finding_text = f"{finding.title} {finding.description} {finding.recommendation}"
            overlap = excerpt_tokens & {
                token for token in _semantic_tokens(finding_text) if len(token) >= 2
            }
            if overlap:
                related.append((len(overlap), finding, sorted(overlap, key=len, reverse=True)[:6]))
        related.sort(key=lambda item: item[0], reverse=True)
        match["related_findings"] = [finding.title for _, finding, _ in related[:3]]
        match["current_evidence"] = [
            {
                "finding": finding.title,
                "shared_terms": shared_terms,
                "evidence": [
                    {
                        "source": evidence.source,
                        "locator": evidence.locator,
                        "excerpt": evidence.excerpt,
                    }
                    for evidence in finding.evidence[:2]
                ],
            }
            for _, finding, shared_terms in related[:3]
        ]
        if not any(item["evidence"] for item in match["current_evidence"]):
            fallback = _best_current_material_evidence(match["excerpt"], documents)
            if fallback:
                match["current_evidence"].append(fallback)
        if match["related_findings"]:
            joined = "、".join(match["related_findings"])
            match["comparison_status"] = "存在需逐条核验的本次发现"
            shared = sorted(
                {term for item in match["current_evidence"] for term in item["shared_terms"]},
                key=len,
                reverse=True,
            )[:6]
            shared_text = "、".join(shared) or "相关业务表述"
            match["comparison"] = (
                f"该依据与本次“{joined}”在“{shared_text}”上存在共同语义或数值。"
                "请以两侧引用原文核对适用范围、版本效力、"
                "审批或执行证据，再决定是否构成违反、例外或需升级事项。"
            )
        elif match["document_type"] == "历史案例":
            match["comparison_status"] = "存在相似的已确认历史事项"
            match["comparison"] = "当前材料与该已确认历史案件相近，请核对问题成因和整改措施是否复发。"
        else:
            match["comparison_status"] = "未关联到规则发现，需核验适用性"
            match["comparison"] = (
                "检索命中该依据，但当前规则未形成直接发现；负责人仍需核对适用范围和执行证据，"
                "不得仅凭相关度判定合规。"
            )
    return matches


def _best_current_material_evidence(
    knowledge_excerpt: str, documents: list[Any]
) -> dict[str, Any] | None:
    """为无规则证据的检索命中定位最相近的当前材料原文。"""

    knowledge_tokens = {
        token for token in _semantic_tokens(knowledge_excerpt) if len(token) >= 2
    }
    candidates: list[tuple[int, str, int, str, list[str]]] = []
    for document in documents:
        for position, current_chunk in enumerate(_chunk_text(document.text)):
            overlap = knowledge_tokens & {
                token for token in _semantic_tokens(current_chunk) if len(token) >= 2
            }
            if overlap:
                candidates.append(
                    (
                        len(overlap),
                        document.name,
                        position,
                        current_chunk,
                        sorted(overlap, key=len, reverse=True)[:6],
                    )
                )
    if not candidates:
        return None
    _, source, position, excerpt, shared_terms = max(candidates, key=lambda item: item[0])
    return {
        "finding": "当前材料语义命中",
        "shared_terms": shared_terms,
        "evidence": [
            {"source": source, "locator": f"第 {position + 1} 个材料分块", "excerpt": excerpt}
        ],
    }


def _chunk_text(text: str, chunk_size: int = 700, overlap: int = 100) -> list[str]:
    """按段落切分知识正文，长段落使用固定重叠窗口。"""

    paragraphs = [item.strip() for item in re.split(r"\n\s*\n|(?<=[。；！？])\s*", text) if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            step = max(1, chunk_size - overlap)
            chunks.extend(paragraph[start : start + chunk_size] for start in range(0, len(paragraph), step))
        elif not current:
            current = paragraph
        elif len(current) + len(paragraph) + 1 <= chunk_size:
            current += "\n" + paragraph
        else:
            chunks.append(current)
            current = paragraph
    if current:
        chunks.append(current)
    return chunks or [text[:chunk_size]]


def _semantic_tokens(text: str) -> list[str]:
    """生成带业务同义词扩展的中英文字符 n-gram。"""

    normalized = text.lower()
    expansions: list[str] = []
    for group in _SYNONYM_GROUPS:
        if any(term.strip() in normalized for term in group):
            expansions.extend(term.strip() for term in group)
    normalized += " " + " ".join(expansions)
    tokens = re.findall(r"[a-z0-9][a-z0-9_.-]*", normalized)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        tokens.extend(sequence)
        tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
        tokens.extend(sequence[index : index + 3] for index in range(len(sequence) - 2))
    return tokens


def _comparison_text(match: dict[str, Any]) -> str:
    """给检索命中生成明确但不越权的对照提示。"""

    if match["document_type"] == "历史案例":
        return "当前材料与该已确认历史案件的问题语义相近，请核对问题是否再次发生。"
    if match["document_type"] == "公司章程":
        return "当前事项触及公司治理依据，请核对决策层级、授权边界和议事程序。"
    return "当前材料与该制度条款语义相关，请核对适用范围、版本效力及实际执行是否一致。"


_DISCLAIMER = "以下内容仅为保利酒店类集团的工作台规划样本，不代表保利酒店现行制度，投产前须由企业负责人替换并确认。"
_HOTEL_BASELINE = [
    {
        "title": "酒店集团公司章程与授权边界（规划样本）",
        "department": "公司级",
        "document_type": "公司章程",
        "content": f"{_DISCLAIMER}\n重大投资、对外担保、关联交易和年度预算调整应按授权清单提交相应治理机构审议。管理层不得拆分交易规避审批。",
    },
    {
        "title": "酒店采购与供应商审计办法（规划样本）",
        "department": "审计与合同",
        "document_type": "部门制度",
        "content": f"{_DISCLAIMER}\n酒店工程、食品原料和客用品采购应保留询比价、供应商准入、验收及付款证据。审计重点识别拆单、围标、关联供应商和验收付款倒挂。",
    },
    {
        "title": "酒店经营收入审计规范（规划样本）",
        "department": "审计与合同",
        "document_type": "业务规范",
        "content": f"{_DISCLAIMER}\n客房、餐饮、宴会和会员渠道收入应与PMS、POS、合同、发票及银行流水核对。异常折扣、免单、冲销和夜审差异应逐项留痕。",
    },
    {
        "title": "酒店劳动用工与排班制度（规划样本）",
        "department": "人力管理",
        "document_type": "部门制度",
        "content": f"{_DISCLAIMER}\n劳动合同、岗位、工作地点、工时制度和加班补休应一致。客房、餐饮等倒班岗位应保留排班与考勤记录，跨酒店调派须明确期限。",
    },
    {
        "title": "酒店招聘与关键岗位任用规范（规划样本）",
        "department": "人力管理",
        "document_type": "业务规范",
        "content": f"{_DISCLAIMER}\n财务、采购、工程和信息系统关键岗位应完成岗位资格、背景核验、利益冲突声明和试用期评价，不得仅依据模型评分作出录用决定。",
    },
    {
        "title": "酒店印章档案与会议管理制度（规划样本）",
        "department": "行政管理",
        "document_type": "部门制度",
        "content": f"{_DISCLAIMER}\n合同用印应核验审批单和定稿文件，严禁空白用印。经营会议决定应明确责任部门、负责人、完成期限和验收标准，并形成逾期升级机制。",
    },
    {
        "title": "酒店安全运营与证照管理规范（规划样本）",
        "department": "行政管理",
        "document_type": "业务规范",
        "content": f"{_DISCLAIMER}\n消防、食品经营、特种设备和公共场所证照应建立到期台账。重大活动、施工改造和外包作业应完成安全评估及应急预案。",
    },
    {
        "title": "酒店费用报销与资金支付制度（规划样本）",
        "department": "财务管理",
        "document_type": "部门制度",
        "content": f"{_DISCLAIMER}\n费用必须匹配预算、合同、发票和验收依据。申请人、审核人和付款人应职责分离；招待费、差旅费和采购付款按金额阈值逐级审批。",
    },
    {
        "title": "酒店预算与经营分析规范（规划样本）",
        "department": "财务管理",
        "document_type": "业务规范",
        "content": f"{_DISCLAIMER}\n预算按酒店、部门、科目和月份跟踪。入住率、平均房价、RevPAR、餐饮毛利、人工成本率及能耗偏差应结合历史同期和滚动预测分析。",
    },
]
