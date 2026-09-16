import { BrowserRouter, Navigate, NavLink, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth';
import { CardListPage } from './pages/CardListPage';
import { CardPage } from './pages/CardPage';
import { LoginPage } from './pages/LoginPage';
import { TeacherReportPage } from './pages/TeacherReportPage';
import { TeacherScenariosPage } from './pages/TeacherScenariosPage';

function Header({ teacher }: { teacher: boolean }) {
  const { user, signOut } = useAuth();
  return (
    <header className="app-header">
      <div>
        <div className="app-header__brand">АРМ-112</div>
        <div className="app-header__sub">Учебный комплекс подготовки диспетчеров ДДС</div>
      </div>

      {teacher && (
        <nav className="app-nav">
          <NavLink to="/scenarios" className={({ isActive }) => (isActive ? 'active' : '')}>
            Сценарии
          </NavLink>
          <NavLink to="/report" className={({ isActive }) => (isActive ? 'active' : '')}>
            Отчёт
          </NavLink>
        </nav>
      )}

      <div className="app-header__spacer" />
      <div className="app-header__user">
        <div>{user?.full_name}</div>
        <div style={{ opacity: 0.8 }}>
          {user?.service_name ?? (teacher ? 'преподаватель' : 'без привязки к службе')}
        </div>
      </div>
      <button className="app-header__logout" onClick={signOut}>
        Выход
      </button>
    </header>
  );
}

export default function App() {
  const { user, loading } = useAuth();

  if (loading) return <div className="empty">Загрузка…</div>;
  if (!user) return <LoginPage />;

  const teacher = user.role === 'teacher' || user.role === 'admin';

  return (
    <BrowserRouter>
      <Header teacher={teacher} />
      <main className="layout">
        <Routes>
          {teacher ? (
            <>
              <Route path="/scenarios" element={<TeacherScenariosPage />} />
              <Route path="/report" element={<TeacherReportPage />} />
              <Route path="*" element={<Navigate to="/scenarios" replace />} />
            </>
          ) : (
            <>
              <Route path="/" element={<CardListPage />} />
              <Route path="/cards/:id" element={<CardPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </>
          )}
        </Routes>
      </main>
    </BrowserRouter>
  );
}
