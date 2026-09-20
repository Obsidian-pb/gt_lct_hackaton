import { BrowserRouter, Navigate, NavLink, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth';
import { AdminAuditPage } from './pages/AdminAuditPage';
import { AdminUsersPage } from './pages/AdminUsersPage';
import { CardListPage } from './pages/CardListPage';
import { CardPage } from './pages/CardPage';
import { LoginPage } from './pages/LoginPage';
import { MaterialsManagePage } from './pages/MaterialsManagePage';
import { MaterialsPage } from './pages/MaterialsPage';
import { OperatorCallPage } from './pages/OperatorCallPage';
import { OperatorCallsPage } from './pages/OperatorCallsPage';
import { StudentProgressPage } from './pages/StudentProgressPage';
import { TeacherGroupsPage } from './pages/TeacherGroupsPage';
import { TeacherReportPage } from './pages/TeacherReportPage';
import { TeacherSessionPage } from './pages/TeacherSessionPage';
import { TeacherSessionsPage } from './pages/TeacherSessionsPage';
import { TeacherScenariosPage } from './pages/TeacherScenariosPage';

function Header({ role }: { role: string }) {
  const { user, signOut } = useAuth();
  return (
    <header className="app-header">
      <div>
        <div className="app-header__brand">АРМ-112</div>
        <div className="app-header__sub">Учебный комплекс подготовки диспетчеров ДДС</div>
      </div>

      <nav className="app-nav">
        {role === 'admin' ? (
          <>
            <NavLink to="/users" className={({ isActive }) => (isActive ? 'active' : '')}>
              Учётные записи
            </NavLink>
            <NavLink to="/audit" className={({ isActive }) => (isActive ? 'active' : '')}>
              Журнал аудита
            </NavLink>
          </>
        ) : role === 'teacher' ? (
          <>
            <NavLink to="/scenarios" className={({ isActive }) => (isActive ? 'active' : '')}>
              Сценарии
            </NavLink>
            <NavLink to="/groups" className={({ isActive }) => (isActive ? 'active' : '')}>
              Группы
            </NavLink>
            <NavLink to="/sessions" className={({ isActive }) => (isActive ? 'active' : '')}>
              Занятия
            </NavLink>
            <NavLink to="/report" className={({ isActive }) => (isActive ? 'active' : '')}>
              Отчёт
            </NavLink>
            <NavLink to="/materials" className={({ isActive }) => (isActive ? 'active' : '')}>
              Справочная база
            </NavLink>
          </>
        ) : (
          <>
            <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
              Карточки ДДС
            </NavLink>
            <NavLink to="/calls" className={({ isActive }) => (isActive ? 'active' : '')}>
              Приём вызовов 112
            </NavLink>
            <NavLink to="/progress" className={({ isActive }) => (isActive ? 'active' : '')}>
              Мои результаты
            </NavLink>
            <NavLink to="/materials" className={({ isActive }) => (isActive ? 'active' : '')}>
              Справочная база
            </NavLink>
          </>
        )}
      </nav>

      <div className="app-header__spacer" />
      <div className="app-header__user">
        <div>{user?.full_name}</div>
        <div style={{ opacity: 0.8 }}>
          {user?.service_name ??
            (role === 'admin'
              ? 'администратор'
              : role === 'teacher'
                ? 'преподаватель'
                : 'без привязки к службе')}
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

  return (
    <BrowserRouter>
      <Header role={user.role} />
      <main className="layout">
        <Routes>
          {user.role === 'admin' ? (
            <>
              <Route path="/users" element={<AdminUsersPage />} />
              <Route path="/audit" element={<AdminAuditPage />} />
              <Route path="*" element={<Navigate to="/users" replace />} />
            </>
          ) : user.role === 'teacher' ? (
            <>
              <Route path="/scenarios" element={<TeacherScenariosPage />} />
              <Route path="/groups" element={<TeacherGroupsPage />} />
              <Route path="/sessions" element={<TeacherSessionsPage />} />
              <Route path="/sessions/:id" element={<TeacherSessionPage />} />
              <Route path="/report" element={<TeacherReportPage />} />
              <Route path="/materials" element={<MaterialsManagePage />} />
              <Route path="*" element={<Navigate to="/scenarios" replace />} />
            </>
          ) : (
            <>
              <Route path="/" element={<CardListPage />} />
              <Route path="/cards/:id" element={<CardPage />} />
              <Route path="/calls" element={<OperatorCallsPage />} />
              <Route path="/calls/:id" element={<OperatorCallPage />} />
              <Route path="/progress" element={<StudentProgressPage />} />
              <Route path="/materials" element={<MaterialsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </>
          )}
        </Routes>
      </main>
    </BrowserRouter>
  );
}
