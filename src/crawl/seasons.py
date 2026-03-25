from datetime import datetime

def season_window(current_year: int | None = None, keep: int = 5) -> list[int]:
    if current_year is None:
        current_year = datetime.now().year
    return list(range(current_year, current_year - keep, -1))

if __name__ == "__main__":
    print(season_window())