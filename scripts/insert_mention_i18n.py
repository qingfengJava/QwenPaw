# -*- coding: utf-8 -*-
"""向 console 七语言 locale 插入「对话修改 + @ 提及」i18n 键（幂等）。

键清单：
- agentDetail.docEditChat / docEditChatTitle / docEditPrompt（档案区入口）
- chat.mentionLoading / mentionEmpty / mentionGroupFile /
  mentionGroupSkill / mentionGroupTool（@ 提及菜单）
"""
import json
from pathlib import Path

ROOT = Path(r"d:\enterprise_code\xxd\QwenPaw\console\src\locales")

AGENT_DETAIL_KEYS = {
    "docEditChat": {
        "zh": "对话修改",
        "en": "Edit via Chat",
        "ja": "チャットで編集",
        "ru": "Изменить в чате",
        "vi": "Chỉnh sửa qua chat",
        "id": "Edit via Chat",
        "pt-BR": "Editar via chat",
    },
    "docEditChatTitle": {
        "zh": "针对当前文件 {{file}} 发起对话修改",
        "en": "Start a chat edit for {{file}}",
        "ja": "{{file}} のチャット編集を開始",
        "ru": "Изменить {{file}} через чат",
        "vi": "Bắt đầu chỉnh sửa {{file}} qua chat",
        "id": "Mulai edit {{file}} via chat",
        "pt-BR": "Iniciar edição de {{file}} via chat",
    },
    "docEditPrompt": {
        "zh": "帮我编辑 @ {{file}}，在开始前请先向我确认具体需要修改的内容",
        "en": (
            "Help me edit @ {{file}}. Please confirm with me what exactly "
            "to change before starting."
        ),
        "ja": (
            "@ {{file}} の編集を手伝ってください。始める前に具体的な変更"
            "内容を私に確認してください。"
        ),
        "ru": (
            "Помоги мне отредактировать @ {{file}}. Перед началом уточни "
            "у меня, что именно нужно изменить."
        ),
        "vi": (
            "Giúp tôi chỉnh sửa @ {{file}}. Trước khi bắt đầu, hãy xác nhận "
            "với tôi những nội dung cần thay đổi cụ thể."
        ),
        "id": (
            "Bantu saya mengedit @ {{file}}. Sebelum mulai, konfirmasi "
            "dulu ke saya apa saja yang perlu diubah."
        ),
        "pt-BR": (
            "Ajude-me a editar @ {{file}}. Antes de começar, confirme "
            "comigo o que exatamente deve ser alterado."
        ),
    },
}

CHAT_KEYS = {
    "mentionLoading": {
        "zh": "加载中…",
        "en": "Loading…",
        "ja": "読み込み中…",
        "ru": "Загрузка…",
        "vi": "Đang tải…",
        "id": "Memuat…",
        "pt-BR": "Carregando…",
    },
    "mentionEmpty": {
        "zh": "无匹配项",
        "en": "No matches",
        "ja": "一致する項目がありません",
        "ru": "Нет совпадений",
        "vi": "Không có kết quả",
        "id": "Tidak ada yang cocok",
        "pt-BR": "Nenhuma correspondência",
    },
    "mentionGroupFile": {
        "zh": "档案",
        "en": "Docs",
        "ja": "ドキュメント",
        "ru": "Документы",
        "vi": "Hồ sơ",
        "id": "Dokumen",
        "pt-BR": "Documentos",
    },
    "mentionGroupSkill": {
        "zh": "技能",
        "en": "Skill",
        "ja": "スキル",
        "ru": "Навык",
        "vi": "Kỹ năng",
        "id": "Skill",
        "pt-BR": "Habilidade",
    },
    "mentionGroupTool": {
        "zh": "工具",
        "en": "Tool",
        "ja": "ツール",
        "ru": "Инструмент",
        "vi": "Công cụ",
        "id": "Tool",
        "pt-BR": "Ferramenta",
    },
}

LANGS = ("zh", "en", "ja", "ru", "vi", "id", "pt-BR")


def main() -> None:
    for lang in LANGS:
        path = ROOT / f"{lang}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        agent_detail = data.setdefault("agentDetail", {})
        chat = data.setdefault("chat", {})
        inserted = 0
        for key, translations in AGENT_DETAIL_KEYS.items():
            if key in agent_detail:
                continue
            agent_detail[key] = translations[lang]
            inserted += 1
        for key, translations in CHAT_KEYS.items():
            if key in chat:
                continue
            chat[key] = translations[lang]
            inserted += 1
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{lang}: +{inserted} keys")


if __name__ == "__main__":
    main()
