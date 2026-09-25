# Parche fijo: `server ... resolve` en upstream exige nginx >= 1.27.3 y un tag
# flotante cacheado viejo en el servidor no arrancaria.
FROM nginx:1.27.5-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
