# -*- coding: utf-8 -*-
"""向 console 七语言 locale 的 workbench 段插入档案历史 i18n 键（幂等）。"""
import json
from pathlib import Path

ROOT = Path(r"d:\enterprise_code\xxd\QwenPaw\console\src\locales")

KEYS = {
    "docHistoryTitle": {
        "zh": "档案历史",
        "en": "Document History",
        "ja": "ドキュメント履歴",
        "ru": "История документов",
        "vi": "Lịch sử hồ sơ",
        "id": "Riwayat Dokumen",
        "pt-BR": "Histórico de documentos",
    },
    "docHistoryHint": {
        "zh": "基础档案的每次发布/回滚快照；回滚直接生效，无需再次发布",
        "en": "Snapshots of base identity docs per publish/rollback; rollback takes effect immediately",
        "ja": "基本ドキュメントの公開・ロールバックごとのスナップショット。ロールバックは即時反映",
        "ru": "Снимки базовых документов при каждой публикации/откате; откат применяется сразу",
        "vi": "Ảnh chụp mỗi lần xuất bản/hoàn tác của hồ sơ cơ bản; hoàn tác có hiệu lực ngay",
        "id": "Cuplikan setiap publikasi/rollback dokumen dasar; rollback langsung aktif",
        "pt-BR": "Snapshots de cada publicação/reversão dos documentos base; a reversão tem efeito imediato",
    },
    "docHistoryUnavailable": {
        "zh": "档案版本链需启用 PostgreSQL 档案存储",
        "en": "Document version chain requires PostgreSQL-backed storage",
        "ja": "ドキュメント履歴には PostgreSQL ストレージが必要です",
        "ru": "Для истории версий документов требуется хранилище PostgreSQL",
        "vi": "Chuỗi phiên bản hồ sơ cần lưu trữ PostgreSQL",
        "id": "Rantai versi dokumen memerlukan penyimpanan PostgreSQL",
        "pt-BR": "O histórico de versões de documentos requer armazenamento PostgreSQL",
    },
    "docHistoryEmpty": {
        "zh": "暂无该档案的版本快照（发布后自动生成）",
        "en": "No snapshots for this document yet (generated on publish)",
        "ja": "このドキュメントのスナップショットはまだありません（公開時に生成）",
        "ru": "Снимков этого документа пока нет (создаются при публикации)",
        "vi": "Chưa có ảnh chụp cho hồ sơ này (tự tạo khi xuất bản)",
        "id": "Belum ada cuplikan untuk dokumen ini (dibuat saat publikasi)",
        "pt-BR": "Ainda não há snapshots deste documento (gerados ao publicar)",
    },
    "docRollbackConfirm": {
        "zh": "回滚 {{file}} 到 v{{version}}？",
        "en": "Roll back {{file}} to v{{version}}?",
        "ja": "{{file}} を v{{version}} にロールバックしますか？",
        "ru": "Откатить {{file}} к v{{version}}?",
        "vi": "Hoàn tác {{file}} về v{{version}}?",
        "id": "Kembalikan {{file}} ke v{{version}}?",
        "pt-BR": "Reverter {{file}} para v{{version}}?",
    },
    "docRollbackHint": {
        "zh": "直接生效线上：production 行 + 工作区文件同步更新",
        "en": "Applies to production immediately: DB row + workspace file updated",
        "ja": "本番に即時反映：権威行とワークスペースファイルを更新",
        "ru": "Применяется сразу: обновляются строка БД и файл рабочей области",
        "vi": "Áp dụng ngay: cập nhật dòng DB + tệp workspace",
        "id": "Langsung berlaku: baris DB + file workspace diperbarui",
        "pt-BR": "Aplica imediatamente: linha do BD + arquivo do workspace atualizados",
    },
    "docRollbackSuccess": {
        "zh": "已回滚 {{file}} 到 v{{version}}，线上已生效",
        "en": "Rolled back {{file}} to v{{version}}; live now",
        "ja": "{{file}} を v{{version}} にロールバックしました（即時反映）",
        "ru": "{{file}} откачен к v{{version}}, изменения применены",
        "vi": "Đã hoàn tác {{file}} về v{{version}}, đã có hiệu lực",
        "id": "{{file}} dikembalikan ke v{{version}}, sudah aktif",
        "pt-BR": "{{file}} revertido para v{{version}}, já em efeito",
    },
}


def main() -> None:
    for lang in ("zh", "en", "ja", "ru", "vi", "id", "pt-BR"):
        path = ROOT / f"{lang}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        workbench = data.setdefault("workbench", {})
        inserted = 0
        for key, translations in KEYS.items():
            if key in workbench:
                continue
            workbench[key] = translations[lang]
            inserted += 1
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{lang}: +{inserted} keys")


if __name__ == "__main__":
    main()
