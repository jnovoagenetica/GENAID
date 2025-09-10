# backend/Dockerfile  — imagen para AWS Lambda (HTTP)
FROM public.ecr.aws/lambda/python:3.11

# 1) Dependencias (se instalan en /var/task, ruta que ejecuta Lambda)
COPY app/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt --target "/var/task"

# 2) Código de la app (copia SOLO lo que importas)
COPY app/ /var/task/app
# Si tu código usa esto, mantenlo; si no existe en tu repo, quita la línea:
COPY embedding_statemachine/ /var/task/embedding_statemachine

# 3) EntryPoint de Lambda: tu main.py define handler = Mangum(app)
CMD ["app.main.handler"]
