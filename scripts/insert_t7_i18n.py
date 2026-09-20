# -*- coding: utf-8 -*-
"""T7 前端 i18n 批量插键（7 语言，zh 为权威源；仿 insert_doc_history_i18n 先例）。

diff 仅新增行：json.load 保序，新键按既有键顺序追加到对应命名空间尾部，
indent=2 + ensure_ascii=False + 结尾换行与仓库现状一致。

@author qingfeng
"""
from __future__ import annotations

import json
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / "console" / "src" / "locales"

# 键 → (zh, en, ja, ru, vi, id, pt-BR)
KB_KEYS: dict[str, tuple[str, ...]] = {
    "kbStatusDraft": ("草稿", "Draft", "下書き", "Черновик", "Bản nháp", "Draf", "Rascunho"),
    "kbStatusInReview": ("审核中", "In Review", "審査中", "На проверке", "Đang duyệt", "Ditinjau", "Em revisão"),
    "kbStatusPublished": ("已发布", "Published", "公開済み", "Опубликовано", "Đã xuất bản", "Diterbitkan", "Publicado"),
    "kbStatusArchived": ("已归档", "Archived", "アーカイブ済み", "В архиве", "Đã lưu trữ", "Diarsipkan", "Arquivado"),
    "governanceTab": ("治理", "Governance", "ガバナンス", "Управление", "Quản trị", "Tata kelola", "Governança"),
    "govDomainPlaceholder": ("按域筛选", "Filter by domain", "ドメインで絞り込み", "Фильтр по домену", "Lọc theo miền", "Filter per domain", "Filtrar por domínio"),
    "govStatusPlaceholder": ("按状态筛选", "Filter by status", "ステータスで絞り込み", "Фильтр по статусу", "Lọc theo trạng thái", "Filter per status", "Filtrar por status"),
    "govStatusNeedsDomain": ("请先选域", "Select a domain first", "先にドメインを選択", "Сначала выберите домен", "Hãy chọn miền trước", "Pilih domain dulu", "Selecione um domínio"),
    "govEmpty": ("暂无知识条目", "No knowledge entries", "知識エントリなし", "Нет записей знаний", "Không có mục kiến thức", "Tidak ada entri pengetahuan", "Sem entradas de conhecimento"),
    "docSource": ("域", "Domain", "ドメイン", "Домен", "Miền", "Domain", "Domínio"),
    "kbStatus": ("状态", "Status", "ステータス", "Статус", "Trạng thái", "Status", "Status"),
    "validity": ("有效期", "Validity", "有効期間", "Срок действия", "Hiệu lực", "Masa berlaku", "Validade"),
    "chunkCount": ("切片", "Chunks", "チャンク", "Фрагменты", "Số khối", "Chunk", "Blocos"),
    "govActions": ("生命周期操作", "Lifecycle actions", "ライフサイクル操作", "Действия ЖЦ", "Thao tác vòng đời", "Aksi siklus hidup", "Ações de ciclo de vida"),
    "reviewSuccess": ("已{{action}}：{{doc}}", "Done {{action}}: {{doc}}", "{{action}}完了：{{doc}}", "Выполнено {{action}}: {{doc}}", "Đã {{action}}: {{doc}}", "Berhasil {{action}}: {{doc}}", "{{action}} concluído: {{doc}}"),
    "reviewConfirm": ("确认{{action}}？", "Confirm {{action}}?", "{{action}}を確認しますか？", "Подтвердить {{action}}?", "Xác nhận {{action}}?", "Konfirmasi {{action}}?", "Confirmar {{action}}?"),
    "action_submit": ("提交审核", "Submit for review", "審査に提出", "Отправить на проверку", "Gửi duyệt", "Kirim untuk ditinjau", "Enviar para revisão"),
    "action_approve": ("通过", "Approve", "承認", "Одобрить", "Phê duyệt", "Setujui", "Aprovar"),
    "action_reject": ("驳回", "Reject", "却下", "Отклонить", "Từ chối", "Tolak", "Rejeitar"),
    "action_archive": ("归档", "Archive", "アーカイブ", "В архив", "Lưu trữ", "Arsipkan", "Arquivar"),
    "conflicts": ("冲突列表", "Conflicts", "コンフリクト一覧", "Конфликты", "Danh sách xung đột", "Daftar konflik", "Conflitos"),
    "conflictsEmpty": ("暂无知识冲突", "No knowledge conflicts", "知識コンフリクトなし", "Нет конфликтов", "Không có xung đột", "Tidak ada konflik", "Sem conflitos"),
    "conflictType": ("类型", "Type", "種別", "Тип", "Loại", "Jenis", "Tipo"),
    "conflictPriority": ("优先级", "Priority", "優先度", "Приоритет", "Ưu tiên", "Prioritas", "Prioridade"),
    "conflictStatus": ("状态", "Status", "ステータス", "Статус", "Trạng thái", "Status", "Status"),
    "conflictResolve": ("解决", "Resolve", "解決", "Решить", "Giải quyết", "Selesaikan", "Resolver"),
    "conflictResolveConfirm": ("确认标记为已解决？", "Mark as resolved?", "解決済みにしますか？", "Отметить как решённый?", "Đánh dấu đã giải quyết?", "Tandai selesai?", "Marcar como resolvido?"),
    "conflictResolved": ("冲突已标记解决", "Conflict resolved", "コンフリクトを解決しました", "Конфликт решён", "Đã giải quyết xung đột", "Konflik diselesaikan", "Conflito resolvido"),
    "bindExpert": ("绑定到我的专家", "Bind to my experts", "マイエキスパートに紐付け", "Привязать к моим экспертам", "Gán vào chuyên gia của tôi", "Ikat ke pakar saya", "Vincular aos meus especialistas"),
    "bindExpertSuccess": ("已绑定到我的专家", "Bound to my expert", "エキスパートに紐付けました", "Привязано к эксперту", "Đã gán vào chuyên gia", "Terikat ke pakar", "Vinculado ao especialista"),
    "bindExpertPlaceholder": ("选择我的专家（数字员工）", "Select my expert (digital employee)", "エキスパートを選択", "Выберите эксперта", "Chọn chuyên gia của tôi", "Pilih pakar saya", "Selecione meu especialista"),
    "bind": ("绑定", "Bind", "紐付け", "Привязать", "Gán", "Ikat", "Vincular"),
    "bindingsEmpty": ("尚未绑定任何专家", "No experts bound yet", "紐付け済みエキスパートなし", "Нет привязанных экспертов", "Chưa gán chuyên gia nào", "Belum ada pakar terikat", "Nenhum especialista vinculado"),
    "unbindConfirm": ("解除该绑定？", "Unbind?", "紐付けを解除しますか？", "Отвязать?", "Gỡ gán?", "Lepas ikatan?", "Desvincular?"),
    "myKbEmpty": ("你还没有个人知识库，可在检索/工作流中创建", "No personal knowledge bases yet", "個人ナレッジベースがありません", "Нет личных баз знаний", "Bạn chưa có cơ sở kiến thức cá nhân", "Belum ada basis pengetahuan pribadi", "Você ainda não tem bases de conhecimento"),
    "refresh": ("刷新", "Refresh", "更新", "Обновить", "Làm mới", "Muat ulang", "Atualizar"),
}

ONTOLOGY_KEYS: dict[str, tuple[str, ...]] = {
    "createObject": ("新建对象", "New Object", "新規オブジェクト", "Новый объект", "Tạo đối tượng", "Objek Baru", "Novo objeto"),
    "createObjectSuccess": ("对象已创建", "Object created", "作成しました", "Объект создан", "Đã tạo đối tượng", "Objek dibuat", "Objeto criado"),
    "editObject": ("编辑对象", "Edit Object", "オブジェクト編集", "Изменить объект", "Sửa đối tượng", "Edit Objek", "Editar objeto"),
    "updateObjectSuccess": ("对象已更新", "Object updated", "更新しました", "Объект обновлён", "Đã cập nhật", "Objek diperbarui", "Objeto atualizado"),
    "removeObjectSuccess": ("对象已删除", "Object deleted", "削除しました", "Объект удалён", "Đã xóa đối tượng", "Objek dihapus", "Objeto excluído"),
    "removeConfirm": ("删除该对象（逻辑删除，可恢复）？", "Delete this object (soft delete)?", "削除しますか（論理削除）？", "Удалить объект (мягко)?", "Xóa đối tượng này (mềm)?", "Hapus objek ini (lunak)?", "Excluir este objeto (suave)?"),
    "remove": ("删除", "Delete", "削除", "Удалить", "Xóa", "Hapus", "Excluir"),
    "statObjects": ("业务对象", "Objects", "オブジェクト", "Объекты", "Đối tượng", "Objek", "Objetos"),
    "typeFilterPlaceholder": ("按类型筛选", "Filter by type", "型で絞り込み", "Фильтр по типу", "Lọc theo loại", "Filter per jenis", "Filtrar por tipo"),
    "searchPlaceholder": ("搜索对象名称", "Search object name", "オブジェクト名を検索", "Поиск по имени", "Tìm theo tên", "Cari nama objek", "Buscar nome do objeto"),
    "objectsEmpty": ("暂无业务对象", "No objects", "オブジェクトなし", "Нет объектов", "Không có đối tượng", "Tidak ada objek", "Sem objetos"),
    "objectName": ("名称", "Name", "名前", "Имя", "Tên", "Nama", "Nome"),
    "objectType": ("类型", "Type", "型", "Тип", "Loại", "Jenis", "Tipo"),
    "objectStatus": ("状态", "Status", "ステータス", "Статус", "Trạng thái", "Status", "Status"),
    "objectAliases": ("别名", "Aliases", "別名", "Псевдонимы", "Bí danh", "Alias", "Apelidos"),
    "objectActions": ("操作", "Actions", "操作", "Действия", "Thao tác", "Aksi", "Ações"),
    "relationsAndLinks": ("关系/关联", "Relations & Links", "関係/リンク", "Связи и ссылки", "Quan hệ & liên kết", "Relasi & tautan", "Relações e links"),
    "relations": ("关系", "Relations", "関係", "Связи", "Quan hệ", "Relasi", "Relações"),
    "relationsEmpty": ("暂无关系", "No relations", "関係なし", "Нет связей", "Không có quan hệ", "Tidak ada relasi", "Sem relações"),
    "relationFrom": ("起点", "From", "起点", "Откуда", "Từ", "Dari", "De"),
    "relationType": ("关系类型", "Relation type", "関係タイプ", "Тип связи", "Loại quan hệ", "Jenis relasi", "Tipo de relação"),
    "relationTo": ("终点对象", "To", "终点", "Куда", "Đến", "Ke", "Para"),
    "removeRelationConfirm": ("删除该关系？", "Delete this relation?", "関係を削除しますか？", "Удалить связь?", "Xóa quan hệ này?", "Hapus relasi ini?", "Excluir esta relação?"),
    "addRelation": ("添加关系", "Add relation", "関係を追加", "Добавить связь", "Thêm quan hệ", "Tambah relasi", "Adicionar relação"),
    "createRelationSuccess": ("关系已创建", "Relation created", "作成しました", "Связь создана", "Đã tạo quan hệ", "Relasi dibuat", "Relação criada"),
    "links": ("关联文档（kb_object_links）", "Linked documents", "関連ドキュメント", "Связанные документы", "Tài liệu liên kết", "Dokumen tertaut", "Documentos vinculados"),
    "linksEmpty": ("暂无关联", "No links", "リンクなし", "Нет ссылок", "Không có liên kết", "Tidak ada tautan", "Sem links"),
    "linkKb": ("知识库 ID", "KB ID", "ナレッジベースID", "ID базы знаний", "ID cơ sở kiến thức", "ID basis pengetahuan", "ID da base"),
    "linkDoc": ("文档 ID", "Document ID", "ドキュメントID", "ID документа", "ID tài liệu", "ID dokumen", "ID do documento"),
    "linkRelation": ("关系", "Relation", "関係", "Связь", "Quan hệ", "Relasi", "Relação"),
    "removeLinkConfirm": ("删除该关联？", "Delete this link?", "リンクを削除しますか？", "Удалить ссылку?", "Xóa liên kết này?", "Hapus tautan ini?", "Excluir este link?"),
    "addLink": ("添加关联", "Add link", "リンクを追加", "Добавить ссылку", "Thêm liên kết", "Tambah tautan", "Adicionar link"),
    "createLinkSuccess": ("关联已创建", "Link created", "作成しました", "Ссылка создана", "Đã tạo liên kết", "Tautan dibuat", "Link criado"),
    "edit": ("编辑", "Edit", "編集", "Изменить", "Sửa", "Edit", "Editar"),
}

NAV_KEYS: dict[str, tuple[str, ...]] = {
    "adminOntology": ("本体管理", "Ontology", "オントロジー", "Онтология", "Quản lý Ontology", "Ontologi", "Ontologia"),
    "myKnowledge": ("我的知识", "My Knowledge", "マイナレッジ", "Мои знания", "Kiến thức của tôi", "Pengetahuan Saya", "Meu Conhecimento"),
}

LANG_ORDER = ["zh", "en", "ja", "ru", "vi", "id", "pt-BR"]


def insert_keys(data: dict, ns: str, keys: dict[str, tuple[str, ...]]) -> None:
    """把 keys 插入 data[ns]（缺命名空间则建），已存在键零改动。"""
    namespace = data.setdefault(ns, {})
    for key, translations in keys.items():
        if key in namespace:
            continue
        idx = LANG_ORDER.index("zh")
        namespace[key] = translations[idx] if ns != "nav" else translations[0]


def apply_namespace(
    data: dict,
    lang: str,
    ns: str,
    keys: dict[str, tuple[str, ...]],
) -> None:
    namespace = data.setdefault(ns, {})
    lang_idx = LANG_ORDER.index(lang)
    for key, translations in keys.items():
        if key in namespace:
            continue
        namespace[key] = translations[lang_idx]


def main() -> None:
    for lang in LANG_ORDER:
        path = LOCALES_DIR / f"{lang}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        apply_namespace(data, lang, "knowledge", KB_KEYS)
        apply_namespace(data, lang, "ontology", ONTOLOGY_KEYS)
        apply_namespace(data, lang, "nav", NAV_KEYS)
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")
        print(f"{lang}: knowledge={len(data.get('knowledge', {}))} "
              f"ontology={len(data.get('ontology', {}))} nav={len(data.get('nav', {}))}")


if __name__ == "__main__":
    main()
