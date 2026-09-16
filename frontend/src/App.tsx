import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth';
import { CardListPage } from './pages/CardListPage';
import { CardPage } from './pages/CardPage';
import { LoginPage } from './pages/LoginPage';

function Header() {
  const { user, signOut } = useAuth();
  return (
    <header className="app-header">
      <div>
        <div className="app-header__brand">АРМ-112</div>
        <div className="app-header__sub">Учебный комплекс подготовки диспетчеров ДДС</div>
      </div>
      <div className="app-header__spacer" />
      <div className="app-header__user">
        <div>{user?.full_name}</div>
        <div style={{ opacity: 0.8 }}>{user?.service_name ?? 'без привязки к службе'}</div>
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
      <Header />
      <main className="layout">
        <Routes>
          <Route path="/" element={<CardListPage />} />
          <Route path="/cards/:id" element={<CardPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
