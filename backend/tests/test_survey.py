"""Опросная карта: навигация по признакам и разбор ошибок классификации."""

import pytest

from app.services.survey import classify, options_at, resolve, survey_tree

FIRE_TRASH = 1010101  # на улице / мусор / открытое пламя -> «пожар: мусор»
SMOKE_TRASH = 1010102  # на улице / мусор / дым -> «задымление: мусор»
FIRES = "Пожары и задымления"


def test_дерево_строится_по_всем_группам():
    tree = survey_tree()
    assert len(tree) == 23
    assert FIRES in tree


def test_выбор_ведёт_к_правилу():
    rule = resolve(FIRES, ["на улице", "мусор", "открытое пламя"])
    assert rule is not None
    assert rule.number == FIRE_TRASH
    assert rule.incident_type == "пожар: мусор"


def test_незавершённый_путь_не_даёт_правила():
    assert resolve(FIRES, ["на улице"]) is None


def test_несуществующий_признак_не_ломает_разбор():
    assert resolve(FIRES, ["на улице", "такого признака нет"]) is None
    assert options_at(FIRES, ["такого признака нет"]) == []


def test_варианты_следующего_шага():
    options = options_at(FIRES, ["на улице", "мусор"])
    labels = {o["label"] for o in options}
    assert {"открытое пламя", "дым"} <= labels
    assert all(o["is_final"] for o in options if o["label"] in {"открытое пламя", "дым"})


def test_верная_классификация():
    result = classify(FIRE_TRASH, FIRES, ["на улице", "мусор", "открытое пламя"])
    assert result.correct is True
    assert result.score == 1.0
    assert result.missed_services == ()


def test_признаки_вызова_учитываются_с_обеих_сторон():
    """Пострадавшие есть у вызова, а не у выбора: список сравнивается при одних флагах.

    Иначе верная классификация с пострадавшими показывала бы «пропущены
    СМП и ЦЭМП» — ошибку, которой обучающийся не совершал.
    """
    exact = classify(
        FIRE_TRASH, FIRES, ["на улице", "мусор", "открытое пламя"], flags={"пострадавшие"}
    )
    assert exact.correct is True
    assert exact.missed_services == ()
    assert exact.extra_services == ()

    # Уход в другую группу оставляет без оповещения все службы эталона —
    # и с пострадавшими среди них скорая, а без них скорой в списке не было.
    wrong = classify(FIRE_TRASH, "Дорожно-транспортные происшествия", ["нет такого"], flags={"пострадавшие"})
    without = classify(FIRE_TRASH, "Дорожно-транспортные происшествия", ["нет такого"])
    assert "СМП" in wrong.missed_services
    assert "СМП" not in without.missed_services


def test_признаки_оператора_считаются_отдельно_от_признаков_вызова():
    """Пострадавшие есть у вызова, оператор кнопку не нажал: скорой в его списке нет.

    Тип при этом верный — ошибка проявляется тем, чем обернулась бы
    в рабочей системе: неоповещённой службой и сниженным баллом.
    """
    result = classify(
        FIRE_TRASH,
        FIRES,
        ["на улице", "мусор", "открытое пламя"],
        flags={"пострадавшие"},
        chosen_flags=frozenset(),
    )
    assert result.correct is True
    assert "СМП" in result.missed_services
    assert result.extra_services == ()
    assert 0 < result.score < 1.0


def test_лишний_признак_оператора_даёт_лишнюю_службу():
    result = classify(
        FIRE_TRASH,
        FIRES,
        ["на улице", "мусор", "открытое пламя"],
        flags=frozenset(),
        chosen_flags={"правонарушение"},
    )
    assert result.correct is True
    assert result.missed_services == ()
    assert "МВД" in result.extra_services
    # Лишняя служба балл за классификацию не снижает: список эталона покрыт.
    assert result.score == 1.0


def test_без_признаков_оператора_обе_стороны_считаются_по_вызову():
    """Карточка диспетчера и кабинет преподавателя признаков оператора не знают."""
    same = classify(
        FIRE_TRASH, FIRES, ["на улице", "мусор", "открытое пламя"], flags={"пострадавшие"}
    )
    explicit = classify(
        FIRE_TRASH,
        FIRES,
        ["на улице", "мусор", "открытое пламя"],
        flags={"пострадавшие"},
        chosen_flags={"пострадавшие"},
    )
    assert same == explicit
    assert same.score == 1.0


def test_ошибка_в_последнем_признаке_даёт_частичный_балл():
    """Дым вместо открытого пламени — ошибка, но путь начат верно."""
    result = classify(FIRE_TRASH, FIRES, ["на улице", "мусор", "дым"])
    assert result.correct is False
    assert result.chosen_rule.number == SMOKE_TRASH
    assert result.matched_depth == 2
    assert 0 < result.score < 1


def test_уход_в_другую_группу_обнуляет_балл():
    result = classify(FIRE_TRASH, "Нарушение правопорядка", ["Подозрительные, посторонние граждане"])
    assert result.correct is False
    assert result.same_group is False
    assert result.score == 0.0


def test_разбор_показывает_неоповещённые_службы():
    """Главное последствие ошибки — на происшествие не поедет нужная служба."""
    result = classify(SMOKE_TRASH, FIRES, ["на улице", "мусор", "открытое пламя"])
    assert result.correct is False
    # Списки оповещения у пожара и задымления различаются.
    assert result.missed_services or result.extra_services


@pytest.mark.parametrize("path", [[], ["на улице"], ["на улице", "мусор"]])
def test_недоклассифицированное_происшествие_без_балла(path):
    result = classify(FIRE_TRASH, FIRES, path)
    assert result.correct is False
    assert result.chosen_rule is None


def test_скрытые_от_оператора_признаки_не_показываются():
    """Такие карточки приходят из внешних систем, оператор их не создаёт."""
    labels = {o["label"] for o in options_at(FIRES, [])}
    assert "Не отображается оператору 112" not in labels
