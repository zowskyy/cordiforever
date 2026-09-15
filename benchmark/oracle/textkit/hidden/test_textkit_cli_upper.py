from textkit.cli import main


def test_upper_flag_anywhere(capsys):
    main(["hello", "--upper", "world"])
    main(["plain", "text"])
    assert capsys.readouterr().out.splitlines() == ["HELLO-WORLD", "plain-text"]
