import re
from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Task

from .serializers import TaskSerializer


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

MINUTE_WORDS = {
    "oh one": 1,
    "oh two": 2,
    "oh three": 3,
    "oh four": 4,
    "oh five": 5,
    "oh six": 6,
    "oh seven": 7,
    "oh eight": 8,
    "oh nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all().order_by("date", "time")
    serializer_class = TaskSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        date = self.request.query_params.get("date")

        if date:
            queryset = queryset.filter(date=date)

        return queryset

    @action(detail=False, methods=["get"])
    def today(self, request):
        today = timezone.localdate()
        tasks = self.get_queryset().filter(date=today)
        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def upcoming(self, request):
        today = timezone.localdate()
        tasks = self.get_queryset().filter(date__gt=today)
        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        today = timezone.localdate()
        queryset = self.get_queryset()

        return Response({
            "pending": queryset.filter(status="pending").count(),
            "completed": queryset.filter(status="completed").count(),
            "priority": queryset.filter(priority="high").count(),
            "overdue": queryset.filter(status="overdue").count(),
            "today": queryset.filter(date=today).count(),
            "upcoming": queryset.filter(date__gt=today).count(),
        })

    @action(detail=False, methods=["get"])
    def calendar(self, request):
        tasks_by_date = {}
        tasks = self.get_queryset()
        serializer = self.get_serializer(tasks, many=True)

        for task in serializer.data:
            date = task["date"]
            if date not in tasks_by_date:
                tasks_by_date[date] = []
            tasks_by_date[date].append(task)

        return Response(tasks_by_date)

    @action(detail=False, methods=["post"], url_path="from-voice")
    def from_voice(self, request):
        transcript = request.data.get("transcript", "").strip()

        if not transcript:
            return Response(
                {"error": "Transcript is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task_data = parse_voice_task(transcript)
        serializer = self.get_serializer(data=task_data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=status.HTTP_201_CREATED)


def parse_voice_task(transcript):
    text = transcript.strip()
    task_date = parse_voice_date(text)
    task_time = parse_voice_time(text)
    priority = parse_voice_priority(text)
    title = clean_voice_title(text)

    return {
        "title": title,
        "description": "",
        "date": task_date,
        "time": task_time,
        "priority": priority,
        "status": "pending",
    }


def parse_voice_date(transcript):
    today = timezone.localdate()
    lowered = transcript.lower()

    if "tomorrow" in lowered:
        return today + timedelta(days=1)

    if "today" in lowered:
        return today

    iso_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", lowered)
    if iso_match:
        return datetime.strptime(iso_match.group(), "%Y-%m-%d").date()

    slash_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", lowered)
    if slash_match:
        month = int(slash_match.group(1))
        day = int(slash_match.group(2))
        year = normalize_year(slash_match.group(3), today.year)
        return datetime(year, month, day).date()

    month_names = "|".join(MONTHS.keys())
    month_match = re.search(
        rf"\b(?:on\s+)?({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b",
        lowered,
    )

    if month_match:
        month = MONTHS[month_match.group(1)]
        day = int(month_match.group(2))
        year = int(month_match.group(3) or today.year)
        return datetime(year, month, day).date()

    return today


def normalize_year(year_text, default_year):
    if not year_text:
        return default_year

    year = int(year_text)
    if year < 100:
        return 2000 + year

    return year


def parse_voice_time(transcript):
    lowered = transcript.lower().replace(".", "")
    number_words = "|".join(NUMBER_WORDS.keys())
    minute_words = "|".join(MINUTE_WORDS.keys())

    time_match = re.search(
        rf"\b(?:at\s+)?(\d{{1,2}}|{number_words})(?::(\d{{2}})|\s+({minute_words}))?\s*(am|pm|a m|p m)\b",
        lowered,
    )

    if not time_match:
        return "09:00:00"

    hour_text = time_match.group(1)
    hour = NUMBER_WORDS.get(hour_text, int(hour_text) if hour_text.isdigit() else 9)
    minute = parse_minute(time_match.group(2), time_match.group(3))
    period = time_match.group(4).replace(" ", "")

    if period == "pm" and hour != 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0

    return f"{hour:02d}:{minute:02d}:00"


def parse_minute(number_text, word_text):
    if number_text:
        return int(number_text)

    if word_text:
        return MINUTE_WORDS.get(word_text, 0)

    return 0


def parse_voice_priority(transcript):
    lowered = transcript.lower()
    priority_match = re.search(r"\bpriority\s+(low|medium|high)\b", lowered)

    if priority_match:
        return priority_match.group(1)

    for priority in ["high", "medium", "low"]:
        if f"{priority} priority" in lowered:
            return priority

    return "medium"


def clean_voice_title(transcript):
    title = transcript.strip()
    title = re.sub(r"^(add|create|schedule)\s+(a\s+)?(task\s+)?", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(today|tomorrow)\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(on\s+)?\d{4}-\d{2}-\d{2}\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(on\s+)?\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", "", title, flags=re.IGNORECASE)
    title = re.sub(
        r"\b(on\s+)?(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(st|nd|rd|th)?(,?\s+\d{4})?\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"\b(at\s+)?(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)(:\d{2}|\s+(oh one|oh two|oh three|oh four|oh five|oh six|oh seven|oh eight|oh nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty))?\s*(am|pm|a m|p m)\b",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\bpriority\s+(low|medium|high)\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(low|medium|high)\s+priority\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" ,.-")

    return title or "Untitled Task"
