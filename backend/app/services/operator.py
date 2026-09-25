"""Приём вызова и заполнение карточки оператором Службы 112.

Оператор слушает заявителя, классифицирует происшествие по опросной карте
и регистрирует адрес с описанием. Итоговый тип и список оповещения
вычисляются классификатором, поэтому оценка здесь полностью детерминирована:
эталон — не мнение модели, а строка ЕКП.

Норматив времени отличается от диспетчерского: 30 секунд ПП РФ № 1931
относятся к подтверждению приёма карточки службой, а оператор всё это время
разговаривает с заявителем.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.training import CallOutcome
from app.services import address as address_service
from app.services import quotes, survey_flags
from app.services.ekp import EKP
from app.services.survey import ClassificationResult, classify
from app.services.violations import Severity, Violation

# Ориентир на обработку одного вызова. Преподаватель может изменить.
DEFAULT_CALL_DEADLINE_SECONDS = 180

SEVERITY_PENALTY = {Severity.CRITICAL: 1.0, Severity.MAJOR: 0.5, Severity.MINOR: 0.25}


@dataclass(frozen=True)
class FilledCard:
    """Что обучающийся внёс в карточку."""

    group: str | None
    path: tuple[str, ...]
    address: str
    description: str
    elapsed_seconds: float
    # Что обучающийся решил сделать с обращением. Прежние вызовы приходят
    # без исхода — для них подразумевается классификация, как было раньше.
    outcome: CallOutcome = CallOutcome.CLASSIFY
    referral_target: str = ""
    # Телефон для связи, записанный со слов заявителя.
    caller_phone: str = ""
    # Адрес по частям: субъект, населённый пункт, улица, дом и подробности.
    address_parts: dict[str, str] = field(default_factory=dict)
    # Признаки опросной карты, которые оператор отметил кнопками:
    # пострадавшие, нет доступа, угроза людям. Список оповещения считается
    # с ними, поэтому неотмеченный признак — не оформление, а пропавшая служба.
    flags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Expected:
    """Эталон обращения: что с ним следовало сделать."""

    outcome: CallOutcome
    rule_number: int | None = None
    referral_target: str | None = None
    # Номер, по которому силы реагирования смогут связаться с заявителем.
    # None — у сценария телефон не задан, и спрашивать его не за что.
    contact_phone: str | None = None
    # Эталонный адрес по частям. Пустой словарь — адрес у вызова
    # описательный, разбирать в нём нечего.
    address_parts: dict[str, str] = field(default_factory=dict)
    # Признаки вызова, влияющие на список оповещения: пострадавшие,
    # газификация, угроза людям. Они заданы сценарием — это то, что
    # заявитель сообщил, — и список оповещения считается с ними.
    flags: frozenset[str] = frozenset()
    # Речь заявителя и адрес, как он назван, — источники цитат к замечаниям:
    # разбор не утверждает «следовало записать дом 21», а показывает, где
    # заявитель это сказал. Пусто — цитат не будет, замечания останутся.
    speech: str = ""
    address_text: str = ""


@dataclass
class OperatorAssessment:
    classification: ClassificationResult | None
    outcome_correct: bool = True
    # Требовалось ли вообще классифицировать происшествие: при передаче
    # по принадлежности и при отказе в регистрации опросная карта не нужна.
    classification_required: bool = True
    violations: list[Violation] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    deadline_seconds: int = DEFAULT_CALL_DEADLINE_SECONDS

    @property
    def score(self) -> float:
        """Балл складывается из классификации и оформления карточки.

        Классификация весит больше остального: от неё зависит, кто поедет
        на происшествие.
        """
        # Неверный исход обесценивает остальное: карточка, заведённая
        # на чужой регион, аккуратна и подробна, но бесполезна — силы
        # реагирования о происшествии не узнают.
        if not self.outcome_correct:
            return 0.0

        classification_score = self.classification.score if self.classification else 0.0
        penalty = sum(
            SEVERITY_PENALTY[v.kind.severity]
            for v in self.violations
            if v.code in {"O5", "O6", "O9", "O11", "O13"}
        )
        paperwork = max(0.0, 1.0 - penalty / 2.0)
        overdue = 1.0 if self.elapsed_seconds > self.deadline_seconds else 0.0
        # Там, где классифицировать не требовалось, весь балл держится
        # на оформлении: адрес и описание нужны и для передачи вызова.
        if self.classification is None and not self.classification_required:
            total = paperwork - 0.1 * overdue
        else:
            total = 0.7 * classification_score + 0.3 * paperwork - 0.1 * overdue
        return round(max(0.0, min(1.0, total)), 3)


def evaluate(
    card: FilledCard,
    expected: Expected | int,
    deadline_seconds: int,
    ekp: EKP | None = None,
) -> OperatorAssessment:
    """Оценивает приём вызова.

    Вторым аргументом принимается эталон целиком; номер правила отдельным
    числом оставлен ради прежних вызовов, где исход всегда был один —
    классификация. Редакция классификатора — редакция занятия: без неё
    берётся встроенная.
    """
    if isinstance(expected, int):
        expected = Expected(outcome=CallOutcome.CLASSIFY, rule_number=expected)

    result = OperatorAssessment(
        classification=None,
        elapsed_seconds=card.elapsed_seconds,
        deadline_seconds=deadline_seconds,
        classification_required=expected.outcome is CallOutcome.CLASSIFY,
    )

    _check_outcome(card, expected, result)

    # Опросную карту разбираем только там, где классификация и требовалась.
    # Признаки, выбранные к вызову из чужого региона, проверять не по чему:
    # правильного правила для него в московском классификаторе нет.
    if expected.outcome is CallOutcome.CLASSIFY and result.outcome_correct:
        if not card.group or not card.path:
            result.violations.append(
                Violation("O1", "Признаки происшествия не выбраны, карточка не классифицирована")
            )
        else:
            # Признаки сверяются только там, где эталон их знает. У сценария
            # без признаков это не «признаков нет», а «признаки не размечены»:
            # наказывать оператора за верно услышанных пострадавших, о которых
            # эталон молчит, значило бы учить не слушать заявителя.
            flags_known = bool(expected.flags)
            classification = classify(
                expected.rule_number,
                card.group,
                list(card.path),
                ekp,
                expected.flags,
                chosen_flags=card.flags if flags_known else None,
            )
            result.classification = classification
            _check_classification(classification, result)
            if flags_known:
                _check_flags(card, expected, classification, result)

    if not card.address.strip():
        result.violations.append(Violation("O5", "Адрес происшествия не внесён в карточку"))
    if not card.description.strip():
        result.violations.append(Violation("O6", "Описание происшествия не внесено"))
    _check_phone(card, expected, result)
    _check_address(card, expected, result)

    # Превышение ориентира по времени снижает балл, но отдельным нарушением
    # не считается: разговор с заявителем может затянуться по его вине.
    return result


# Названия субъектов обучающийся пишет по-разному: «МО», «Московская обл.»,
# «Московская область». Сверять дословно значило бы штрафовать за форму
# записи, а не за существо, поэтому сравниваются ключевые слова.
REGION_ALIASES: dict[str, tuple[str, ...]] = {
    # «мо» здесь быть не должно: как подстрока оно находится внутри слова
    # «Москва», и столица засчиталась бы за область — то самое смешение,
    # которое вызов и проверяет. Сокращение опознаётся отдельным словом ниже.
    "московская область": ("московск", "подмосков"),
    "тульская область": ("тульск",),
    "рязанская область": ("рязан",),
    "владимирская область": ("владимирск",),
    "волгоградская область": ("волгоградск", "волжск"),
}


def _same_region(answer: str, expected: str) -> bool:
    """Совпадает ли названный субъект с эталонным."""
    answer = answer.strip().lower().replace("ё", "е")
    expected = expected.strip().lower().replace("ё", "е")
    if not answer:
        return False
    # Столица и область — разные субъекты, и путать их нельзя ни в какую
    # сторону, хотя названия схожи.
    if {answer, expected} == {"москва", "московская область"}:
        return False
    if expected in answer or answer in expected:
        return True
    for keys in REGION_ALIASES.get(expected, ()):
        if keys in answer:
            return True
    # «МО» как сокращение опознаётся только отдельным словом: иначе оно
    # нашлось бы внутри любого слова с этими буквами.
    return expected.startswith("московск") and answer in {"мо", "м.о.", "м/о"}


def _check_outcome(card: FilledCard, expected: Expected, result: OperatorAssessment) -> None:
    """Сверяет решение обучающегося о судьбе обращения с эталонным.

    Это первое, что оператор обязан понять: наше ли это происшествие
    и происшествие ли вообще. Ошибка здесь дороже ошибки в признаках —
    при ней вызов целиком уходит не туда или не уходит никуда.
    """
    if card.outcome is expected.outcome:
        if expected.outcome is CallOutcome.REFER and not card.referral_target.strip():
            result.violations.append(
                Violation("O9", "Не указан субъект, которому передаётся вызов")
            )
        elif expected.outcome is CallOutcome.REFER and expected.referral_target:
            if not _same_region(card.referral_target, expected.referral_target):
                result.violations.append(
                    Violation(
                        "O9",
                        f"Вызов передан в «{card.referral_target.strip()}», "
                        f"адрес относится к «{expected.referral_target}»",
                        evidence=card.referral_target.strip(),
                    )
                )
        return

    result.outcome_correct = False

    if expected.outcome is CallOutcome.REFER:
        where = expected.referral_target or "другой субъект"
        if card.outcome is CallOutcome.CLASSIFY:
            result.violations.append(
                Violation(
                    "O7",
                    f"Происшествие зарегистрировано как московское, "
                    f"адрес относится к «{where}» — вызов следовало передать "
                    f"по принадлежности",
                    evidence=card.address.strip() or None,
                    quote=_subject_quote(expected),
                )
            )
        else:
            result.violations.append(
                Violation(
                    "O10",
                    "Происшествие не зарегистрировано и не передано: "
                    f"вызов следовало передать в «{where}»",
                )
            )
    elif expected.outcome is CallOutcome.REJECT:
        result.violations.append(
            Violation(
                "O10",
                "Обращение не является происшествием для Системы-112, "
                "регистрировать его не следовало",
            )
        )
    else:
        # Эталон — классификация, а обучающийся от неё отказался.
        result.violations.append(
            Violation(
                "O8",
                "Происшествие в зоне ответственности Москвы "
                + (
                    "передано по принадлежности"
                    if card.outcome is CallOutcome.REFER
                    else "отклонено как не являющееся происшествием"
                ),
                evidence=card.address.strip() or None,
            )
        )


def _check_address(card: FilledCard, expected: Expected, result: OperatorAssessment) -> None:
    """Сверяет адрес по частям.

    Разделение на два нарушения не формальное: без субъекта, города, улицы
    или дома на место вообще не выехать, а без подъезда и кода домофона
    бригада доедет до дома и будет искать вход. Это разные по цене ошибки.
    """
    if not expected.address_parts:
        return

    check = address_service.compare(expected.address_parts, card.address_parts)
    if check.ok:
        return

    critical = check.critical_missing
    if critical:
        result.violations.append(
            Violation(
                "O12",
                "Не уточнено: " + ", ".join(address_service.AddressCheck.titles(critical)),
                evidence=", ".join(f"{k}={v}" for k, v in card.address_parts.items()) or None,
                quote=_parts_quote(expected, critical),
            )
        )

    minor = [part for part in check.missing if part not in critical]
    if minor:
        result.violations.append(
            Violation(
                "O13",
                "Не записано: "
                + ", ".join(address_service.AddressCheck.titles(tuple(minor))),
                quote=_parts_quote(expected, tuple(minor)),
            )
        )

    if check.wrong:
        # Неверная часть адреса хуже незаписанной: по ней поедут не туда,
        # а незаписанную хотя бы переспросят.
        code = "O12" if any(
            part.split(":")[0] in {"субъект", "населённый пункт", "улица", "дом"}
            for part in check.wrong
        ) else "O13"
        result.violations.append(
            Violation(
                code,
                "; ".join(check.wrong),
                quote=_parts_quote(expected, tuple(w.split(":")[0] for w in check.wrong), by_title=True),
            )
        )


def _digits(value: str) -> str:
    """Только цифры: «916-126-34-71», «8 916 1263471» и «+7 916…» — один номер.

    Придираться к форме записи телефона значит проверять не то: оператор
    записывает номер на слух, и разделители у каждого свои.
    """
    digits = "".join(ch for ch in value if ch.isdigit())
    # Междугородний и международный префиксы отбрасываются: 8 916… и 7 916…
    # — тот же абонент.
    if len(digits) == 11 and digits[0] in {"7", "8"}:
        return digits[1:]
    return digits


def _check_phone(card: FilledCard, expected: Expected, result: OperatorAssessment) -> None:
    """Записан ли телефон для связи, и тот ли.

    Проверяется только там, где у сценария телефон есть: у части учебных
    вызовов он не задан, и требовать его было бы придиркой к пустому месту.
    """
    if not expected.contact_phone:
        return

    answer = _digits(card.caller_phone)
    if not answer:
        result.violations.append(
            Violation("O11", "Телефон для связи с заявителем не внесён в карточку")
        )
        return

    if answer != _digits(expected.contact_phone):
        result.violations.append(
            Violation(
                "O11",
                f"Записан телефон {card.caller_phone.strip()}, "
                f"заявитель назвал другой",
                evidence=card.caller_phone.strip(),
                quote=quotes.find_digits(expected.speech, expected.contact_phone or ""),
            )
        )


def _check_classification(
    classification: ClassificationResult, result: OperatorAssessment
) -> None:
    if classification.correct:
        return

    expected = classification.expected_rule
    if classification.chosen_rule is None:
        result.violations.append(
            Violation(
                "O1",
                "Выбор признаков не доведён до итогового типа происшествия",
                evidence=f"следовало: {expected.incident_type}",
            )
        )
    elif not classification.same_group:
        result.violations.append(
            Violation(
                "O2",
                f"Выбрана группа «{classification.chosen_rule.group}», "
                f"следовало «{expected.group}»",
                evidence=classification.chosen_rule.incident_type,
            )
        )
    else:
        result.violations.append(
            Violation(
                "O3",
                f"Зарегистрирован тип «{classification.chosen_rule.incident_type}», "
                f"следовало «{expected.incident_type}»",
                evidence=classification.chosen_rule.incident_type,
            )
        )

    if classification.missed_services:
        result.violations.append(
            Violation(
                "O4",
                "Из-за ошибки в классификации не были бы оповещены: "
                + _services_list(list(classification.missed_services)),
                evidence=f"{len(classification.missed_services)} служб",
            )
        )


def _services_list(services: list[str]) -> str:
    listed = ", ".join(services[:6])
    more = len(services) - 6
    return listed + (f" и ещё {more}" if more > 0 else "")


def _check_flags(
    card: FilledCard,
    expected: Expected,
    classification: ClassificationResult,
    result: OperatorAssessment,
) -> None:
    """Сверяет признаки, отмеченные оператором, с признаками вызова.

    Признак сам по себе не оценивается — только его последствия для списка
    оповещения. «Нет доступа» на пожаре мусора ничего не меняет: МЧС
    оповещается и так, лишь через другую подколонку; такое расхождение
    нарушением не считается. А без «пострадавших» на том же пожаре
    не поедет скорая — это и есть ошибка, и разбор называет её службами,
    а не ключом признака.

    Последствия считаются по эталонному правилу: что список потерял бы без
    этого признака и что приобрёл бы с лишним. Считать по выбранному
    правилу нельзя — при ошибке в типе оно другое, и пропуск признака
    смешался бы с ошибкой классификации, которая разобрана отдельно.
    """
    rule = classification.expected_rule
    reference = set(rule.resolve(expected.flags))

    for flag in sorted(expected.flags - card.flags):
        lost = sorted(reference - set(rule.resolve(expected.flags - {flag})))
        if not lost:
            continue
        result.violations.append(
            Violation(
                "O14",
                f"Не отмечен признак «{flag.replace('_', ' ')}»: без него не были бы "
                f"оповещены {_services_list(lost)}",
                evidence=f"{len(lost)} служб",
                quote=_flag_quote(expected, flag),
            )
        )

    for flag in sorted(card.flags - expected.flags):
        added = sorted(set(rule.resolve(expected.flags | {flag})) - reference)
        if not added:
            continue
        result.violations.append(
            Violation(
                "O15",
                f"Отмечен признак «{flag.replace('_', ' ')}», которого в вызове нет: "
                f"без оснований оповещены {_services_list(added)}",
                evidence=flag,
            )
        )


# --- Цитаты к замечаниям ------------------------------------------------------
#
# Каждая цитата — дословный кусок речи заявителя или названного им адреса.
# Не нашлась — замечание остаётся без неё; сочинять цитату нельзя.


def _subject_quote(expected: Expected) -> str | None:
    """Где заявитель назвал регион: «Тульская обл., дорога от Киреевска…»."""
    if not expected.referral_target:
        return None
    for word in expected.referral_target.split():
        if len(word) > 4 and (found := quotes.find(expected.address_text, word[:-2])):
            return found
    return None


def _parts_quote(expected: Expected, parts: tuple[str, ...], by_title: bool = False) -> str | None:
    """Место в адресе, где названа первая из пропущенных или неверных частей."""
    titles = {title: key for key, title in address_service.PARTS}
    for part in parts:
        key = titles.get(part.strip(), part) if by_title else part
        value = (expected.address_parts.get(key) or "").strip()
        if value and (found := quotes.find(expected.address_text, value)):
            return found
    return None


def _flag_quote(expected: Expected, flag: str) -> str | None:
    """Место в речи, где заявитель назвал признак: «…5 пострадавших…»."""
    pattern = survey_flags.pattern_for(flag)
    return quotes.find_any(expected.speech, pattern) if pattern else None
