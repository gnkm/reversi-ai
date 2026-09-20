import { useCallback, useEffect, useState } from "react";
import { CatalogPage } from "./pages/CatalogPage.tsx";
import { GamePage } from "./pages/GamePage.tsx";
import type { CatalogItem, GameState } from "./types.ts";

function currentPath(): string {
  return window.location.pathname;
}

function go(path: string): void {
  window.history.pushState(null, "", path);
}

function nameMap(items: readonly CatalogItem[]): Map<string, string> {
  return new Map(items.map((item) => [item.specimen_id, item.display_name]));
}

export function App() {
  const [path, setPath] = useState(() => currentPath());
  const [game, setGame] = useState<GameState | null>(null);
  const [items, setItems] = useState<CatalogItem[]>([]);

  const onGame = useCallback((next: GameState) => {
    setGame(next);
  }, []);

  useEffect(() => {
    const onPop = () => setPath(currentPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function showCatalog() {
    setGame(null);
    go("/");
    setPath("/");
  }

  function handleStarted(next: GameState, catalog: readonly CatalogItem[]) {
    setItems([...catalog]);
    setGame(next);
    go("/game");
    setPath("/game");
  }

  if (path === "/game" && game !== null) {
    return (
      <GamePage
        game={game}
        specimenNames={nameMap(items)}
        onGame={onGame}
        onBack={showCatalog}
      />
    );
  }

  if (path === "/game") {
    return (
      <main className="page">
        <h1>盤面</h1>
        <p>進行中の対局がありません。</p>
        <button type="button" className="btn-primary" onClick={showCatalog}>
          カタログへ戻る
        </button>
      </main>
    );
  }

  return <CatalogPage onStarted={handleStarted} />;
}
