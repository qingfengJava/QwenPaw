/**
 * 「更多」— 应用/灵感 extension page (sidebar entry).
 * First release: empty-state placeholder in the prototype design language.
 */
export default function MorePage() {
  return (
    <div className="page-list">
      <div className="projects-header-area">
        <div className="projects-header-left">
          <h1>更多</h1>
          <p>应用与灵感，敬请期待</p>
        </div>
      </div>
      <div className="blank-state">
        <i className="fa-solid fa-border-all" style={{ fontSize: 28, marginBottom: 12 }} />
        <div>应用市场与灵感中心即将上线</div>
      </div>
    </div>
  );
}
