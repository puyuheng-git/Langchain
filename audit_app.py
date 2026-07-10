#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 审计工作台 - Web 可视化界面（Streamlit）

这是审计工作台的图形界面版本，复用 audit/ 包的全部逻辑：
- CLI 版（main.py /review）和 Web 版共用同一条审阅管道
- 界面只负责「上传文件、展示结果」，不含任何业务逻辑
  （这就是「界面与逻辑分离」：以后换 Web 框架也不用动 audit/）

什么是 Streamlit？
- 一个用纯 Python 写 Web 界面的库，不用学 HTML/JS
- 脚本从上到下执行一遍 = 渲染一次页面
- 用户每次交互（点按钮、选文件）都会「重新跑一遍脚本」，
  所以需要 st.session_state 来「记住」跨交互的数据

运行方式:
    streamlit run audit_app.py
    然后浏览器自动打开 http://localhost:8501
"""

# ============================================
# 导入依赖
# ============================================

# streamlit 是 Web 界面框架，约定俗成缩写为 st
import streamlit as st

# Path 用于文件路径处理
from pathlib import Path

# datetime 用于显示报告时间
from datetime import datetime

# 导入配置（拿数据目录路径）
from config import Config

# 导入合同审阅管道（核心逻辑全在这里，界面只是调用它）
from audit import ContractReviewPipeline

# ============================================
# 页面全局配置
# ============================================

# set_page_config 必须是第一个 st 调用，设置浏览器标签页标题和布局
# layout="wide" 用宽屏布局，表格和风险清单能显示更多内容
st.set_page_config(
    page_title="AI 审计工作台",
    page_icon="📑",
    layout="wide",
)

# 上传文件的临时保存目录（audit 管道需要「磁盘上的文件路径」）
UPLOADS_DIR = Config.DATA_DIR / "uploads"

# 审阅底稿目录（与 CLI 版共用，历史页从这里读）
REPORTS_DIR = Config.DATA_DIR / "reports"

# 风险等级 → Streamlit 提示框样式的映射
# st.error 红色 / st.warning 黄色 / st.info 蓝色，天然对应 高/中/低
LEVEL_TO_BOX = {"高": st.error, "中": st.warning, "低": st.info}

# 风险等级 → emoji（与 CLI 报告保持一致）
LEVEL_ICONS = {"高": "🔴", "中": "🟡", "低": "🟢"}


# ============================================
# 管道的缓存初始化
# ============================================

# @st.cache_resource 装饰器：让管道只创建一次并全局复用
# 没有它的话，用户每点一次按钮脚本重跑，管道就重建一次（浪费时间）
@st.cache_resource
def get_pipeline() -> ContractReviewPipeline:
    """
    创建（或复用已缓存的）合同审阅管道

    Returns:
        ContractReviewPipeline 实例
    """
    # 第一次调用时真正创建，之后 Streamlit 自动返回缓存的实例
    return ContractReviewPipeline()


# ============================================
# 结果展示函数
# ============================================

def show_review_result(result: dict) -> None:
    """
    展示一份合同的完整审阅结果

    对应 CLI 版 ReportGenerator.display() 的 Web 版本。

    Args:
        result: ContractReviewPipeline.review() 的返回值
    """
    # ----- 合同基本信息 -----
    contract = result["contract"]

    # st.columns 把一行分成多列，用来放统计卡片
    col1, col2, col3 = st.columns(3)
    # st.metric 显示「标签 + 大数字」的统计卡片
    col1.metric("📄 页数", contract["page_count"])
    col2.metric("🔤 字符数", contract["char_count"])

    # 统计风险数量（给第三张卡片用）
    risks = result["risks"]["risks"] if result["risks"]["success"] else []
    high_count = sum(1 for r in risks if r["level"] == "高")
    col3.metric("⚠️ 高风险", high_count)

    # 截断提示（审计场景必须让用户知道「看的不是全文」）
    if contract["truncated"]:
        st.warning("⚠ 合同过长已截断，以下分析仅覆盖前部分内容")

    # ----- 关键要素表 -----
    st.subheader("📋 关键要素")

    extraction = result["extraction"]
    if extraction["success"]:
        # 延迟导入字段说明字典（和报告生成器共用同一份定义）
        from audit.extractor import EXTRACTION_FIELDS

        # 把字段字典转成「行列表」，喂给 st.table
        rows = []
        for key, label in EXTRACTION_FIELDS.items():
            value = extraction["fields"].get(key)
            rows.append({
                # 取说明的括号前主干做行名（如「甲方（全称）」→「甲方」）
                "要素": label.split("（")[0],
                # None 显示为「—」
                "内容": str(value) if value is not None else "—",
            })
        # st.table 渲染静态表格（不可排序但显示全部内容，适合底稿风格）
        st.table(rows)
    else:
        # 提取失败时显示错误
        st.error(f"关键字段提取失败: {extraction['error']}")

    # ----- 风险清单 -----
    st.subheader(f"⚠️ 风险清单（共 {len(risks)} 条）")

    if not result["risks"]["success"]:
        st.error(f"风险识别失败: {result['risks']['error']}")
    elif not risks:
        # 没有风险时明确说明（审计的「无保留意见」）
        st.success("✅ 未识别出明显风险条款")
    else:
        # 逐条渲染风险，等级决定提示框颜色（红/黄/蓝）
        for i, risk in enumerate(risks, start=1):
            # 从映射表取对应的提示框函数
            box = LEVEL_TO_BOX[risk["level"]]
            icon = LEVEL_ICONS[risk["level"]]
            # Markdown 格式拼接：条款加粗，分析和建议分行
            box(
                f"{icon} **{i}. [{risk['level']}] {risk['clause']}**\n\n"
                f"**风险分析**: {risk['reason']}\n\n"
                f"**审计建议**: {risk['suggestion']}"
            )

    # ----- 底稿下载 -----
    # 审阅时已自动保存 Markdown 底稿，这里提供下载按钮
    if result["report_path"] and Path(result["report_path"]).exists():
        # 读取底稿内容（bytes 模式，下载按钮需要）
        report_bytes = Path(result["report_path"]).read_bytes()
        st.download_button(
            label="⬇️ 下载审阅底稿 (Markdown)",
            data=report_bytes,
            file_name=Path(result["report_path"]).name,
            mime="text/markdown",
            # key 避免多份合同的下载按钮冲突
            key=f"download_{result['file_name']}",
        )


def show_batch_summary(results: list) -> None:
    """
    展示批量审阅的汇总表（多文件上传时）

    Args:
        results: 多份合同的审阅结果列表
    """
    st.subheader("📊 批量审阅汇总")

    # 构建汇总表的行数据
    rows = []
    for r in results:
        if not r["success"]:
            # 失败的合同也要出现在汇总里（审计留痕）
            rows.append({
                "合同": r.get("file_name", "未知"),
                "高风险": "—", "中风险": "—", "低风险": "—",
                "状态": "❌ 失败",
            })
            continue

        # 统计各等级风险数
        risks = r["risks"]["risks"] if r["risks"]["success"] else []
        high = sum(1 for x in risks if x["level"] == "高")
        mid = sum(1 for x in risks if x["level"] == "中")
        low = sum(1 for x in risks if x["level"] == "低")
        rows.append({
            "合同": r["file_name"],
            "高风险": high, "中风险": mid, "低风险": low,
            # 有高风险就标「需关注」
            "状态": "⚠️ 需关注" if high > 0 else "✅ 正常",
        })

    # 渲染汇总表
    st.table(rows)


# ============================================
# 页面 1: 审阅合同
# ============================================

def page_review() -> None:
    """
    「审阅合同」页面：上传 → 审阅 → 展示结果
    """
    st.title("📑 合同审阅")
    st.caption("上传合同（PDF/TXT/MD），AI 自动提取关键要素并识别风险条款")

    # 文件上传组件
    # accept_multiple_files=True 允许一次选多份合同（批量审）
    uploaded_files = st.file_uploader(
        "选择合同文件",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
    )

    # 没选文件时给出引导提示并提前返回
    if not uploaded_files:
        st.info("👆 请先上传合同文件（支持多选做批量审阅）")
        return

    # 「开始审阅」按钮：type="primary" 显示为醒目的主按钮
    if st.button(f"🔍 开始审阅（{len(uploaded_files)} 份）", type="primary"):
        # 确保上传目录存在
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

        # 获取（缓存的）审阅管道
        pipeline = get_pipeline()

        # 逐份审阅上传的合同
        results = []
        # st.progress 显示进度条（0.0 ~ 1.0）
        progress = st.progress(0.0, text="准备审阅...")

        for i, uploaded in enumerate(uploaded_files):
            # 更新进度条和提示文字
            progress.progress(
                i / len(uploaded_files),
                text=f"正在审阅 [{i + 1}/{len(uploaded_files)}]: {uploaded.name}",
            )

            # Streamlit 上传的是「内存中的字节」，
            # 而管道需要「磁盘文件路径」，所以先落盘
            save_path = UPLOADS_DIR / uploaded.name
            # getbuffer() 拿到上传文件的字节内容
            save_path.write_bytes(uploaded.getbuffer())

            # 调用审阅管道（与 CLI 版完全同一套逻辑）
            result = pipeline.review(str(save_path))
            results.append(result)

        # 完成后进度条拉满
        progress.progress(1.0, text="✅ 审阅完成")

        # 把结果存进 session_state（Streamlit 每次交互会重跑脚本，
        # 不存的话点一下下载按钮结果就消失了）
        st.session_state["review_results"] = results

    # ----- 展示结果（从 session_state 读，跨交互保持） -----
    results = st.session_state.get("review_results")
    if not results:
        return

    # 多份合同时先显示汇总表
    if len(results) > 1:
        show_batch_summary(results)

    # 逐份展示详情
    for result in results:
        if not result["success"]:
            # 失败的合同显示错误信息
            st.error(f"❌ {result.get('file_name', '未知')}: {result['error']}")
            continue

        if len(results) > 1:
            # 多份时用折叠面板（expander）收纳每份详情，页面不至于太长
            with st.expander(f"📄 {result['file_name']} 审阅详情"):
                show_review_result(result)
        else:
            # 单份时直接平铺展示
            st.divider()
            st.header(f"📄 {result['file_name']}")
            show_review_result(result)


# ============================================
# 页面 2: 历史底稿
# ============================================

def page_history() -> None:
    """
    「历史底稿」页面：浏览/下载已保存的审阅底稿
    """
    st.title("📚 历史底稿")
    st.caption("查看过往审阅生成的 Markdown 底稿（CLI 和 Web 版共用）")

    # 底稿目录不存在或为空时提示
    if not REPORTS_DIR.exists():
        st.info("还没有任何审阅底稿，先去「合同审阅」页审一份吧")
        return

    # 收集所有 .md 底稿，按修改时间倒序（最新的在前）
    # key=... 按文件修改时间排序，reverse=True 倒序
    reports = sorted(
        REPORTS_DIR.glob("*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not reports:
        st.info("还没有任何审阅底稿，先去「合同审阅」页审一份吧")
        return

    # 下拉框选择要看的底稿
    # format_func 自定义显示格式：文件名 + 修改时间
    selected = st.selectbox(
        f"选择底稿（共 {len(reports)} 份）",
        reports,
        format_func=lambda p: (
            f"{p.name}  "
            f"({datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')})"
        ),
    )

    # 读取选中的底稿内容
    content = selected.read_text(encoding="utf-8")

    # 提供下载按钮
    st.download_button(
        label="⬇️ 下载此底稿",
        data=content.encode("utf-8"),
        file_name=selected.name,
        mime="text/markdown",
    )

    st.divider()

    # 直接渲染 Markdown（底稿本身就是 Markdown 格式，天然适合展示）
    st.markdown(content)


# ============================================
# 主入口: 侧边栏导航
# ============================================

def main() -> None:
    """
    应用主入口：侧边栏选择页面并渲染
    """
    # 侧边栏标题
    st.sidebar.title("📑 AI 审计工作台")
    st.sidebar.caption("财务审计 · 内部审计 · 合同审阅")

    # 单选导航：选中哪个就渲染哪个页面
    page = st.sidebar.radio(
        "功能导航",
        ["📑 合同审阅", "📚 历史底稿"],
    )

    # 侧边栏底部显示当前模型配置（方便确认用的是哪个 LLM）
    st.sidebar.divider()
    st.sidebar.caption(f"Provider: {Config.LLM_PROVIDER}")
    st.sidebar.caption(f"Model: {Config.DEFAULT_MODEL}")

    # 根据选择渲染对应页面
    if page == "📑 合同审阅":
        page_review()
    else:
        page_history()


# 直接运行脚本时（streamlit run audit_app.py）执行 main
# 注意：streamlit 其实每次都会执行整个脚本，这个判断只是习惯写法
if __name__ == "__main__":
    main()
