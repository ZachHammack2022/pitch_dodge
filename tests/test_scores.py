from pitch_dodge.scores import KEEP, Entry, ScoreBoard


def entry(score):
    return Entry(score=score, best_streak=1, cleared=False, date="2026-01-01")


def test_empty_board(tmp_path):
    board = ScoreBoard(tmp_path / "s.json")
    assert board.best("song", "normal") == 0
    assert board.top("song", "normal") == []


def test_submit_ranks_and_persists(tmp_path):
    path = tmp_path / "nested" / "s.json"
    board = ScoreBoard(path)
    assert board.submit("song", "normal", entry(100)) == 1
    assert board.submit("song", "normal", entry(50)) == 2
    assert board.submit("song", "normal", entry(200)) == 1

    reloaded = ScoreBoard(path)
    assert [e.score for e in reloaded.top("song", "normal")] == [200, 100, 50]
    assert reloaded.best("song", "hard") == 0  # difficulties are separate


def test_board_keeps_only_top_entries(tmp_path):
    board = ScoreBoard(tmp_path / "s.json")
    for s in range(KEEP):
        board.submit("song", "easy", entry(100 + s))
    assert board.submit("song", "easy", entry(1)) is None
    assert len(board.top("song", "easy")) == KEEP


def test_corrupt_file_is_ignored(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    board = ScoreBoard(path)
    assert board.best("song", "normal") == 0
    board.submit("song", "normal", entry(10))
    assert ScoreBoard(path).best("song", "normal") == 10
