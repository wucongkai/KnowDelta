import { useState } from 'react'
import { NavLink, Route, Routes, Link } from 'react-router-dom'
import { BookOpen, ChevronRight, FolderOpen, Layers3, Menu, Plus, Settings2, X } from 'lucide-react'
import Library from './pages/Library'
import Reader from './pages/Reader'
import Settings from './pages/Settings'
import ImportDialog from './components/ImportDialog'

export default function App() {
  const [importOpen, setImportOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        跳转到主要内容
      </a>
      <aside className={'sidebar ' + (menuOpen ? 'mobile-open' : '')}>
        <Link className="brand" to="/" onClick={() => setMenuOpen(false)}>
          <span className="brand-symbol">
            <BookOpen size={22} />
          </span>
          <div>
            <strong>
              KnowDelta<span>知微</span>
            </strong>
            <small>让知识有迹可循</small>
          </div>
        </Link>
        <button
          className="icon-button mobile-close"
          onClick={() => setMenuOpen(false)}
          aria-label="关闭导航"
        >
          <X size={20} />
        </button>
        <button
          className="button primary sidebar-create"
          onClick={() => {
            setImportOpen(true)
            setMenuOpen(false)
          }}
        >
          <Plus size={18} />
          新建笔记<span className="key-hint">＋</span>
        </button>
        <div className="nav-label">工作空间</div>
        <nav>
          <NavLink to="/" end onClick={() => setMenuOpen(false)}>
            <FolderOpen size={19} />
            我的笔记
          </NavLink>
          <NavLink to="/processing" onClick={() => setMenuOpen(false)}>
            <Layers3 size={19} />
            处理任务
          </NavLink>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-thought">
            <span className="tiny-star">✳</span>
            <p>
              学习，是把别人的经验
              <br />
              变成自己的理解。
            </p>
            <span>STAY CURIOUS.</span>
          </div>
          <NavLink className="settings-link" to="/settings" onClick={() => setMenuOpen(false)}>
            <Settings2 size={18} />
            工作区设置
            <ChevronRight size={15} />
          </NavLink>
          <div className="profile">
            <span className="avatar">K</span>
            <div>
              <strong>我的学习空间</strong>
              <small>
                <span className="live-dot on" />
                本地工作区
              </small>
            </div>
          </div>
        </div>
      </aside>
      {menuOpen && (
        <button className="mobile-scrim" aria-label="关闭导航" onClick={() => setMenuOpen(false)} />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div>
            <button
              className="icon-button mobile-menu"
              aria-label="打开导航"
              onClick={() => setMenuOpen(true)}
            >
              <Menu size={21} />
            </button>
            <BookOpen size={16} />
            <span>学习工作台</span>
            <ChevronRight size={13} />
            <span className="topbar-muted">让知识持续生长</span>
          </div>
          <span className="workspace-pill">
            <span />
            个人工作区
          </span>
        </header>
        <main id="main">
          <Routes>
            <Route path="/" element={<Library onImport={() => setImportOpen(true)} />} />
            <Route
              path="/processing"
              element={<Library key="processing" activeOnly onImport={() => setImportOpen(true)} />}
            />
            <Route path="/notes/:id" element={<Reader />} />
            <Route path="/settings" element={<Settings />} />
            <Route
              path="*"
              element={
                <div className="empty-state">
                  <h1>这一页还没有笔记</h1>
                  <Link className="button secondary" to="/">
                    返回笔记库
                  </Link>
                </div>
              }
            />
          </Routes>
        </main>
      </div>
      <ImportDialog open={importOpen} onOpenChange={setImportOpen} />
    </div>
  )
}
