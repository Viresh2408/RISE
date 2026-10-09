{{- define "rise-api.name" -}}rise-api{{- end -}}

{{- define "rise-api.selectorLabels" -}}
app: rise-api
{{- end -}}

{{- define "rise-api.labels" -}}
app: rise-api
app.kubernetes.io/name: rise-api
app.kubernetes.io/part-of: rise
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
environment: {{ .Values.environment }}
{{- end -}}
